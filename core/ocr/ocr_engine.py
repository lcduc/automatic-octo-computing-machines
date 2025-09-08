# Standard library imports
import logging
import os
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed
import asyncio
import psutil
import subprocess

# Third-party imports (optional)
try:
    import torch
    from PIL import Image
    from pdf2image import convert_from_bytes
    import cv2
    import numpy as np
    
    # Use Windows-specific OCR import fix
    from .windows_ocr_fix import get_ocr_availability, safe_import_paddleocr, safe_import_vietocr
    
    # Check OCR availability with Windows fixes
    paddleocr_available, vietocr_available, OCR_DEPENDENCIES_AVAILABLE = get_ocr_availability()
    
    if OCR_DEPENDENCIES_AVAILABLE:
        # Import OCR modules safely
        if paddleocr_available:
            PaddleOCR, _ = safe_import_paddleocr()
        else:
            PaddleOCR = None
            
        if vietocr_available:
            Predictor, Cfg, _ = safe_import_vietocr()
        else:
            Predictor = None
            Cfg = None
    else:
        PaddleOCR = None
        Predictor = None
        Cfg = None

except ImportError as e:
    torch = None
    Image = None
    convert_from_bytes = None
    PaddleOCR = None
    Predictor = None
    Cfg = None
    # Instead of setting cv2 and np to None, raise ImportError if used and not available
    OCR_DEPENDENCIES_AVAILABLE = False

# Local imports
from .ocr_utils import setup_temp_directory
from config.ocr.ocr_config import OCRConfig

logger = logging.getLogger(__name__)


class OCREngine:
    """OCR processor with fallback capabilities."""

    def __init__(self):
        self.ocr_available = False
        self.detector = None
        self.recognitor = None
        self.device_info = {
            "detector": "Not initialized",
            "recognitor": "Not initialized",
        }
        self.temp_dir = setup_temp_directory()
        self._initialize_ocr()

    def log_resource_usage(self, context=""):
        """Log current CPU and GPU utilization."""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            logger.info(f"[RES] {context} CPU usage: {cpu_percent}%")
        except Exception as e:
            logger.warning(f"[RES] {context} CPU usage unavailable: {e}")
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            gpu_info = result.stdout.strip()
            logger.info(f"[RES] {context} GPU usage: {gpu_info}")
        except Exception as e:
            logger.warning(f"[RES] {context} GPU usage unavailable: {e}")

    def _cleanup_corrupted_model(self):
        """Clean up corrupted VietOCR model files and force re-download."""
        try:
            # Common cache directories where VietOCR might store models
            cache_dirs = [
                os.path.expanduser("~/.cache/torch/hub/checkpoints"),
                os.path.expanduser("~/AppData/Local/Temp"),
                os.path.join(
                    os.path.expanduser("~"), ".cache", "torch", "hub", "checkpoints"
                ),
                os.path.join(os.path.expanduser("~"), "AppData", "Local", "Temp"),
            ]

            # Add environment-specific cache directories
            torch_home = os.getenv("TORCH_HOME")
            if torch_home:
                cache_dirs.append(os.path.join(torch_home, "hub", "checkpoints"))
            transformers_cache = os.getenv("TRANSFORMERS_CACHE")
            if transformers_cache:
                cache_dirs.append(transformers_cache)

            corrupted_files_found = []

            for cache_dir in cache_dirs:
                if os.path.exists(cache_dir):
                    logger.info(f"🔍 Checking cache directory: {cache_dir}")
                    for filename in os.listdir(cache_dir):
                        if "vgg_transformer" in filename.lower() or filename.endswith(
                            ".pth"
                        ):
                            file_path = os.path.join(cache_dir, filename)
                            try:
                                # Try to open the file to check if it's corrupted
                                with open(file_path, "rb") as f:
                                    # Read first few bytes to check if it's a valid file
                                    header = f.read(8)
                                    if not header or len(header) < 8:
                                        logger.warning(
                                            f"⚠️ Found corrupted model file: {file_path}"
                                        )
                                        corrupted_files_found.append(file_path)
                            except Exception as e:
                                logger.warning(
                                    f"⚠️ Found unreadable model file: {file_path} - {e}"
                                )
                                corrupted_files_found.append(file_path)

            # Remove corrupted files
            from utils.file_utils import FileUtils

            for file_path in corrupted_files_found:
                try:
                    if FileUtils.safe_delete_file(file_path):
                        logger.info(f"🗑️ Removed corrupted model file: {file_path}")
                    else:
                        logger.warning(
                            f"⚠️ Failed to remove corrupted file {file_path}: Could not delete file"
                        )
                except Exception as e:
                    logger.warning(
                        f"⚠️ Failed to remove corrupted file {file_path}: {e}"
                    )

            if corrupted_files_found:
                logger.info(
                    f"🧹 Cleaned up {len(corrupted_files_found)} corrupted model files"
                )
                return True
            else:
                logger.info("✅ No corrupted model files found")
                return False

        except Exception as e:
            logger.warning(f"⚠️ Error during model cleanup: {e}")
            return False

    def _safe_ocr_call(self, img_path: str, detection_only: bool = False):
        """Safely call PaddleOCR with numpy array error handling."""
        try:
            if detection_only:
                result = self.detector.ocr(img_path, cls=False, det=True, rec=False)  # type: ignore
            else:
                result = self.detector.ocr(img_path, cls=False)  # type: ignore

            # Always convert numpy arrays to lists immediately
            if result and len(result) > 0:
                ocr_result = result[0]
                if ocr_result is not None and hasattr(ocr_result, "tolist"):
                    ocr_result = ocr_result.tolist()
                return ocr_result
            return None

        except ValueError as e:
            if "ambiguous" in str(e).lower():
                logger.debug(f"Numpy array ambiguity in PaddleOCR call: {e}")
                return None
            else:
                raise e

    def _initialize_ocr(self):
        """Initialize OCR engines with improved GPU/CPU fallback and batch processing."""
        if not OCR_DEPENDENCIES_AVAILABLE:
            logger.warning(
                "⚠️ OCR dependencies not available - OCR functionality will be disabled"
            )
            logger.info(
                "💡 Install OCR dependencies: pip install vietocr paddleocr pdf2image torchvision opencv-python numpy"
            )
            self.ocr_available = False
            return

        try:
            # Check GPU availability
            self.use_gpu = torch and torch.cuda.is_available()
            logger.info(f"🔍 GPU availability check: {self.use_gpu}")

        # Initialize PaddleOCR detector with optimized settings for speed
            try:
                logger.info(
                    f"🚀 Initializing PaddleOCR with {'GPU' if self.use_gpu else 'CPU'}..."
                )
                self.detector = PaddleOCR(  # type: ignore
                    use_angle_cls=False,  # Disable angle classification for speed
                    lang="vi",
                    use_gpu=self.use_gpu,
                    show_log=False,  # Reduce verbose logging
                    det_max_side_len=960,  # Reduce max side length for speed
                    rec_batch_num=8,  # Optimize batch processing
                )
                self.device_info["detector"] = "GPU" if self.use_gpu else "CPU"
                logger.info(
                    f"✅ PaddleOCR initialized with {'GPU' if self.use_gpu else 'CPU'} (device_info: {self.device_info['detector']})"
                )
            except Exception as e:
                if self.use_gpu:
                    logger.warning(f"⚠️ GPU initialization failed for PaddleOCR: {e}")
                    logger.info("🔄 Falling back to CPU for PaddleOCR...")
                    try:
                        self.detector = PaddleOCR(use_angle_cls=False, lang="vi", use_gpu=False, show_log=False)  # type: ignore
                        self.device_info["detector"] = "CPU"
                        self.use_gpu = False  # Force CPU for consistency
                        logger.info("✅ PaddleOCR CPU fallback successful")
                    except Exception as cpu_e:
                        logger.warning(f"⚠️ PaddleOCR CPU fallback also failed: {cpu_e}")
                        self.detector = None
                        self.device_info["detector"] = "Failed to initialize"
                else:
                    logger.warning(f"⚠️ PaddleOCR initialization failed: {e}")
                    self.detector = None
                    self.device_info["detector"] = "Failed to initialize"

            # Initialize VietOCR recognizer with batch processing support
            try:
                logger.info(
                    f"🚀 Initializing VietOCR with {'GPU' if self.use_gpu else 'CPU'}..."
                )
                config = Cfg.load_config_from_name("vgg_transformer")  # type: ignore
                config["cnn"]["pretrained"] = True
                config["predictor"]["beamsearch"] = True
                config["device"] = "cuda:0" if self.use_gpu else "cpu"

                self.recognitor = Predictor(config)  # type: ignore
                self.device_info["recognitor"] = "GPU" if self.use_gpu else "CPU"
                logger.info(
                    f"✅ VietOCR initialized with {'GPU' if self.use_gpu else 'CPU'} (device_info: {self.device_info['recognitor']})"
                )
            except Exception as e:
                if "PytorchStreamReader failed reading zip archive" in str(
                    e
                ) or "failed finding central directory" in str(e):
                    logger.warning(f"⚠️ VietOCR model file corrupted: {e}")
                    logger.info("🧹 Cleaning up corrupted model files and retrying...")

                    # Clean up corrupted files
                    if self._cleanup_corrupted_model():
                        logger.info(
                            "🔄 Retrying VietOCR initialization after cleanup..."
                        )
                        try:
                            config = Cfg.load_config_from_name("vgg_transformer")  # type: ignore
                            config["cnn"]["pretrained"] = True
                            config["predictor"]["beamsearch"] = True
                            config["device"] = "cuda:0" if self.use_gpu else "cpu"

                            self.recognitor = Predictor(config)  # type: ignore
                            self.device_info["recognitor"] = (
                                "GPU" if self.use_gpu else "CPU"
                            )
                            logger.info(
                                f"✅ VietOCR initialized successfully after cleanup with {self.device_info['recognitor']}"
                            )
                        except Exception as retry_e:
                            logger.warning(
                                f"⚠️ VietOCR initialization still failed after cleanup: {retry_e}"
                            )
                            self.recognitor = None
                            self.device_info["recognitor"] = "Failed to initialize"
                    else:
                        logger.warning(f"⚠️ VietOCR initialization failed: {e}")
                        self.recognitor = None
                        self.device_info["recognitor"] = "Failed to initialize"
                else:
                    if self.use_gpu:
                        logger.warning(f"⚠️ GPU initialization failed for VietOCR: {e}")
                        logger.info("🔄 Falling back to CPU for VietOCR...")
                        try:
                            config["device"] = "cpu"
                            self.recognitor = Predictor(config)  # type: ignore
                            self.device_info["recognitor"] = "CPU"
                            logger.info("✅ VietOCR CPU fallback successful")
                        except Exception as cpu_e:
                            logger.warning(
                                f"⚠️ VietOCR CPU fallback also failed: {cpu_e}"
                            )
                            self.recognitor = None
                            self.device_info["recognitor"] = "Failed to initialize"
                    else:
                        logger.warning(f"⚠️ VietOCR initialization failed: {e}")
                        self.recognitor = None
                        self.device_info["recognitor"] = "Failed to initialize"

            # Set OCR as available if at least one component is working
            if self.detector or self.recognitor:
                self.ocr_available = True
                working_components = []
                if self.detector:
                    working_components.append("PaddleOCR")
                if self.recognitor:
                    working_components.append("VietOCR")
                logger.info(
                    f"🎉 OCR partially initialized with: {', '.join(working_components)}"
                )
            else:
                self.ocr_available = False
                logger.warning(
                    "⚠️ All OCR components failed to initialize - OCR functionality disabled"
                )

        except Exception as e:
            logger.warning(f"⚠️ OCR initialization encountered an error: {e}")
            logger.info(
                "💡 OCR functionality will be disabled, but the application will continue running"
            )
            self.ocr_available = False

    def get_device_info(self) -> dict:
        """Get information about which devices are being used for OCR."""
        return {
            "ocr_available": self.ocr_available,
            "detector_device": self.device_info.get("detector", "Not initialized"),
            "recognitor_device": self.device_info.get("recognitor", "Not initialized"),
            "gpu_available": self._check_gpu_availability(),
        }

    def _check_gpu_availability(self) -> bool:
        """Check if GPU is available for OCR processing."""
        try:
            return bool(torch and torch.cuda.is_available())
        except:
            return False

    def _preprocess_image(self, pil_img, config=None):
        """
        Preprocess image for OCR: deskew, grayscale, binarization, resize.
        Each step can be toggled via config dict.
        Args:
            pil_img: PIL.Image
            config: dict with keys 'deskew', 'grayscale', 'binarize', 'resize', 'resize_height'
        Returns:
            PIL.Image (processed)
        """
        try:
            import cv2
            import numpy as np
        except ImportError:
            raise ImportError(
                "OpenCV (cv2) and numpy are required for OCR pre-processing."
            )
        if config is None:
            config = {}
        img = np.array(pil_img)
        # Convert RGBA to RGB if needed
        if img.shape[-1] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)
        # Deskew
        if config.get("deskew", True):
            img = self._deskew_image(img)
        # Grayscale
        if config.get("grayscale", True):
            img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        # Contrast Enhancement (CLAHE)
        if config.get("contrast_enhance", True):
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            img = clahe.apply(img)
        # Sharpening
        if config.get("sharpen", True):
            kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
            img = cv2.filter2D(img, -1, kernel)
        # Denoising
        if config.get("denoise", True):
            img = cv2.fastNlMeansDenoising(img, None, 30, 7, 21)
        # Binarization
        if config.get("binarize", True):
            if config.get("adaptive", True):
                img = cv2.adaptiveThreshold(
                    img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 25, 15
                )
            else:
                _, img = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # Resize
        if config.get("resize", True):
            target_height = config.get("resize_height", 32)
            if len(img.shape) == 2:
                h, w = img.shape
            else:
                h, w, _ = img.shape
            if h < target_height:
                scale = target_height / h
                new_w = int(w * scale)
                img = cv2.resize(
                    img, (new_w, target_height), interpolation=cv2.INTER_LINEAR
                )
        # Convert back to PIL
        if Image is None:
            raise ImportError("PIL.Image is not available")
        if len(img.shape) == 2:
            pil_img = Image.fromarray(img)
        else:
            pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        return pil_img

    def _deskew_image(self, img):
        """
        Deskew image using Hough transform to find the dominant angle.
        Args:
            img: np.ndarray (RGB or grayscale)
        Returns:
            np.ndarray (deskewed)
        """
        import cv2
        import numpy as np

        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if len(img.shape) == 3 else img
        blur = cv2.GaussianBlur(gray, (9, 9), 0)
        edges = cv2.Canny(blur, 50, 150, apertureSize=3)
        lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)
        angle = 0.0
        if lines is not None:
            angles = []
            for line in lines:
                for rho, theta in line:
                    angle_deg = (theta * 180 / np.pi) - 90
                    if -45 < angle_deg < 45:
                        angles.append(angle_deg)
            if angles:
                angle = np.median(angles)
        if abs(angle) > 0.1:
            (h, w) = gray.shape
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, float(angle), 1.0)
            img = cv2.warpAffine(
                img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
            )
        return img

    def extract_text_with_ocr(
        self, pdf_content: bytes, preprocess_config=None, num_workers: int = 4
    ) -> List[str]:
        """
        Extract text from PDF using improved OCR with batch processing and pre-processing.
        Args:
            pdf_content: PDF file bytes
            preprocess_config: dict for pre-processing steps
            num_workers: number of parallel workers for page processing
        Returns:
            List of text chunks
        """
        if preprocess_config is None:
            from config.ocr.ocr_config import OCRConfig

            preprocess_config = {
                "deskew": OCRConfig.OCR_DESKEW(),
                "grayscale": OCRConfig.OCR_GRAYSCALE(),
                "binarize": OCRConfig.OCR_BINARIZE(),
                "adaptive": OCRConfig.OCR_BINARIZE_ADAPTIVE(),
                "resize": OCRConfig.OCR_RESIZE(),
                "resize_height": OCRConfig.OCR_RESIZE_HEIGHT(),
                "contrast_enhance": OCRConfig.OCR_CONTRAST_ENHANCE(),
                "sharpen": OCRConfig.OCR_SHARPEN(),
                "denoise": OCRConfig.OCR_DENOISE(),
            }
        if not self.ocr_available:
            if not OCR_DEPENDENCIES_AVAILABLE:
                raise ValueError(
                    "OCR dependencies not available. Install dependencies: pip install vietocr paddleocr pdf2image torchvision opencv-python numpy"
                )
            else:
                raise ValueError(
                    "OCR engines failed to initialize. Check logs for details."
                )
        if not convert_from_bytes:
            raise ValueError("pdf2image not available. Install: pip install pdf2image")
        try:
            images = convert_from_bytes(pdf_content, dpi=300)  # type: ignore
            logger.info(f"\U0001f4c4 Converting PDF to {len(images)} page images")
            all_chunks = []
            import io

            # Prepare arguments for multiprocessing
            args_list = []
            for page_num, img in enumerate(images):
                img_bytes = io.BytesIO()
                img.save(img_bytes, format="PNG")
                args_list.append(
                    (page_num, img_bytes.getvalue(), preprocess_config, self.temp_dir)
                )
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                results = list(executor.map(process_page_for_mp, args_list))
            for page_chunks in results:
                all_chunks.extend(page_chunks)
            logger.info(
                f"\U0001f389 OCR completed: extracted {len(all_chunks)} total text chunks"
            )
            return all_chunks
        except Exception as e:
            logger.error(f"\u274c OCR processing failed: {e}")
            raise ValueError(f"OCR processing failed: {str(e)}")

    async def async_extract_text_with_ocr(
        self, pdf_content: bytes, preprocess_config=None
    ) -> List[str]:
        """
        Async version of extract_text_with_ocr that runs OCR processing in a thread pool.
        This prevents blocking the event loop during CPU/GPU-intensive OCR operations.
        """
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            return await loop.run_in_executor(
                pool, self.extract_text_with_ocr, pdf_content, preprocess_config
            )

    async def async_batch_extract_text_with_ocr(self, file_list):
        """
        Async version of batch_extract_text_with_ocr for concurrent OCR processing.
        """
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            return await loop.run_in_executor(
                pool, self.batch_extract_text_with_ocr, file_list
            )

    def extract_text_from_image_batch(
        self, img_path: str, page_num: int, padding: int = 4
    ) -> List[str]:
        """
        Extract text from image using improved batch processing.

        Args:
            img_path: Path to the image file
            page_num: Page number for labeling
            padding: Padding around detected text regions

        Returns:
            List of text chunks with page labels
        """
        try:
            import time

            t0 = time.time()
            self.log_resource_usage(f"Detection (bbox) page {page_num}")

            # Step 1: Detect bounding boxes only (faster) using safe wrapper
            ocr_result = self._safe_ocr_call(img_path, detection_only=True)
            t1 = time.time()
            logger.info(f"[TIMER] Detection (bbox) page {page_num} took {t1-t0:.2f}s")

            if ocr_result is None:
                logger.debug(
                    f"Safe OCR call returned None for page {page_num}, using fallback"
                )
                return self._extract_text_from_image_fallback(img_path, page_num)

            # Check if empty result
            if not ocr_result or len(ocr_result) == 0:
                logger.debug(f"No text regions detected on page {page_num}")
                return []

            # Step 2: Extract bounding boxes with padding
            boxes = []
            for line in ocr_result:
                try:
                    # Convert line to list if it's a numpy array
                    if hasattr(line, "tolist"):
                        line = line.tolist()

                    # Extract coordinates safely (avoid numpy array comparison)
                    if (
                        line is not None
                        and isinstance(line, (list, tuple))
                        and len(line) >= 4
                    ):
                        coords = line[0]  # First element should be coordinates

                        # Convert coords to list if it's a numpy array
                        if hasattr(coords, "tolist"):
                            coords = coords.tolist()

                        if (
                            coords is not None
                            and isinstance(coords, (list, tuple))
                            and len(coords) >= 4
                        ):
                            (x1, y1), _, (x2, y2), _ = (
                                coords[0],
                                coords[1],
                                coords[2],
                                coords[3],
                            )
                            boxes.append(
                                (
                                    max(int(x1) - padding, 0),
                                    max(int(y1) - padding, 0),
                                    int(x2) + padding,
                                    int(y2) + padding,
                                )
                            )
                except (IndexError, TypeError, ValueError) as e:
                    logger.debug(f"Error extracting bbox from line: {e}")
                    continue

            # Step 3: Crop all text regions
            if Image is None:
                raise ImportError("PIL.Image is not available")
            img = Image.open(img_path)  # type: ignore
            crops = []
            for x1, y1, x2, y2 in boxes:
                crop = img.crop((x1, y1, x2, y2))
                crops.append(crop)

            logger.debug(f"🔍 Found {len(crops)} text regions on page {page_num}")

            # Step 4: Batch recognition (much faster than individual calls)
            t2 = time.time()
            if crops and self.recognitor:
                self.log_resource_usage(f"Recognition (batch) page {page_num}")
                texts = self.recognitor.predict_batch(crops)  # type: ignore
                t3 = time.time()
                logger.info(
                    f"[TIMER] Recognition (batch) page {page_num} took {t3-t2:.2f}s"
                )
                self.log_resource_usage(f"Post-recognition page {page_num}")
            else:
                if not self.recognitor:
                    logger.warning(
                        "VietOCR recognitor not available, using fallback method"
                    )
                    return self._extract_text_from_image_fallback(img_path, page_num)
                texts = []

            # Step 5: Combine text regions into meaningful chunks
            if texts:
                # Combine all text from the page into a single text block
                page_text_parts = []
                for text in texts:
                    if text and isinstance(text, str) and text.strip():  # type: ignore
                        page_text_parts.append(text.strip())  # type: ignore

                if page_text_parts:
                    # Join all text parts with spaces and add page label
                    combined_text = "\n".join(page_text_parts)
                    page_text_with_label = f"Page {page_num}: {combined_text}"

                    # Use the base processor's chunking logic for intelligent splitting
                    from core.processing.processors import BaseProcessor

                    chunks = BaseProcessor.chunk_text(
                        page_text_with_label, chunk_size=1000, overlap=200
                    )
                    return chunks

            return []

        except Exception as e:
            logger.warning(f"⚠️ Batch OCR failed for page {page_num}: {e}")
            # Fallback to old method if batch processing fails
            return self._extract_text_from_image_fallback(img_path, page_num)

    def _extract_text_from_image_fallback(
        self, img_path: str, page_num: int
    ) -> List[str]:
        """
        Fallback method for text extraction using traditional OCR approach.

        Args:
            img_path: Path to the image file
            page_num: Page number for labeling

        Returns:
            List of text chunks with page labels
        """
        try:
            logger.debug(f"🔄 Using fallback OCR method for page {page_num}")

            # Use full OCR (detection + recognition) with safe wrapper
            ocr_result = self._safe_ocr_call(img_path, detection_only=False)

            if ocr_result is None:
                logger.warning(f"Safe OCR call failed for page {page_num}")
                return []

            # Check if empty result (safe wrapper already converted arrays)
            if not ocr_result or len(ocr_result) == 0:
                logger.debug(f"Empty OCR result for page {page_num}")
                return []

            # Extract and combine text from OCR results
            page_text_parts = []
            for line in ocr_result:
                try:
                    # Convert line to list if it's a numpy array to avoid ambiguity
                    if hasattr(line, "tolist"):
                        line = line.tolist()

                    # OCR result format: [[[x1,y1], [x2,y2], [x3,y3], [x4,y4]], (text, confidence)]
                    if (
                        line is not None
                        and isinstance(line, (list, tuple))
                        and len(line) >= 2
                    ):
                        # Extract text and confidence
                        _, (text, confidence) = line[0], line[1]

                        if text and isinstance(text, str) and confidence > 0.5:
                            text_str = text.strip()
                            if text_str:
                                page_text_parts.append(text_str)
                                logger.debug(
                                    f"Text: '{text_str}' (confidence: {confidence:.2f})"
                                )

                except (IndexError, ValueError, TypeError) as e:
                    logger.debug(f"Error parsing OCR line: {e}")
                    continue

            # Combine all text parts and create intelligent chunks
            if page_text_parts:
                # Join all text parts with spaces and add page label
                combined_text = "\n".join(page_text_parts)
                page_text_with_label = f"Page {page_num}: {combined_text}"

                # Use the base processor's chunking logic for intelligent splitting
                from core.processing.processors import BaseProcessor

                chunks = BaseProcessor.chunk_text(
                    page_text_with_label, chunk_size=1000, overlap=200
                )
                logger.debug(
                    f"Fallback method created {len(chunks)} intelligent chunks from {len(page_text_parts)} text parts"
                )
                return chunks

            return []

        except Exception as e:
            logger.warning(f"⚠️ Fallback OCR failed for page {page_num}: {e}")
            return []

    def batch_extract_text_with_ocr(self, file_list):
        """
        Process multiple files sequentially using OCR.
        file_list: List of (filename, file_content) pairs (e.g., [("file1.pdf", b"..."), ...])
        Returns: dict mapping filename to extracted text chunks or error message
        """
        results = {}
        from config.ocr.ocr_config import OCRConfig

        for filename, file_content in file_list:
            try:
                result = self.extract_text_with_ocr(
                    file_content, num_workers=OCRConfig.OCR_MAX_WORKERS()
                )
                results[filename] = result
            except Exception as e:
                results[filename] = f"Error: {e}"
        return results


# Global OCREngine instance for each process
_engine_instance = None


def get_engine_instance():
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = OCREngine()
    return _engine_instance


def process_file_for_mp(args):
    """
    Top-level function for multiprocessing per-file OCR.
    args: (filename, file_content)
    """
    filename, file_content = args
    try:
        engine = get_engine_instance()
        result = engine.extract_text_with_ocr(file_content)
        return (filename, result)
    except Exception as e:
        return (filename, f"Error: {e}")


# Move process_page_for_mp here, after OCREngine is defined, to avoid multiprocessing pickling issues
def process_page_for_mp(args):
    """
    Top-level function for multiprocessing per-page OCR.
    args: (pdf_content, page_num, img_bytes, preprocess_config, temp_dir)
    """
    import uuid
    import os
    import logging
    from PIL import Image
    import io

    logger = logging.getLogger(__name__)
    page_num, img_bytes, preprocess_config, temp_dir = args
    temp_img_path = None
    page_chunks = []
    try:
        img = Image.open(io.BytesIO(img_bytes))
        engine = get_engine_instance()
        processed_img = engine._preprocess_image(img, preprocess_config)
        temp_filename = f"page_{page_num}_{uuid.uuid4().hex[:8]}.png"
        temp_img_path = os.path.join(temp_dir, temp_filename)
        processed_img.save(temp_img_path)
        page_texts = engine.extract_text_from_image_batch(temp_img_path, page_num + 1)
        if page_texts:
            page_chunks.extend(page_texts)
    except Exception as e:
        logger.warning(f"\u26a0\ufe0f OCR failed for page {page_num + 1}: {e}")
    finally:
        if temp_img_path:
            try:
                os.unlink(temp_img_path)
            except:
                pass
    return page_chunks
