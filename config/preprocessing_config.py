"""
Configuration for document preprocessing settings.
"""

from typing import Dict, Any
from pydantic import BaseModel, Field
from core.processing.preprocessing import PreprocessingConfig


class PreprocessingSettings(BaseModel):
    """Pydantic model for preprocessing configuration."""
    
    # Deskewing settings
    deskew_enabled: bool = Field(default=True, description="Enable automatic deskewing")
    deskew_threshold: float = Field(default=0.5, ge=0.1, le=5.0, description="Minimum angle in degrees to trigger deskewing")
    
    # Denoising settings
    denoise_enabled: bool = Field(default=True, description="Enable noise removal")
    denoise_method: str = Field(default="bilateral", description="Denoising method: gaussian, bilateral, median")
    
    # Binarization settings
    binarize_enabled: bool = Field(default=True, description="Enable binarization")
    binarize_method: str = Field(default="otsu", description="Binarization method: otsu, adaptive, threshold")
    
    # Contrast enhancement settings
    contrast_enabled: bool = Field(default=True, description="Enable contrast enhancement")
    contrast_factor: float = Field(default=1.2, ge=1.0, le=3.0, description="Contrast enhancement factor")
    
    # Sharpening settings
    sharpen_enabled: bool = Field(default=True, description="Enable image sharpening")
    sharpen_factor: float = Field(default=1.5, ge=1.0, le=3.0, description="Sharpening strength factor")
    
    # Cropping settings
    crop_margins_enabled: bool = Field(default=True, description="Enable automatic margin cropping")
    margin_threshold: int = Field(default=10, ge=0, le=100, description="Margin threshold in pixels")
    
    # Scaling settings
    scale_enabled: bool = Field(default=True, description="Enable image scaling")
    target_dpi: int = Field(default=300, ge=72, le=600, description="Target DPI for scaling")
    max_scale_factor: float = Field(default=2.0, ge=1.0, le=5.0, description="Maximum scaling factor")
    
    # Artifact removal settings
    remove_artifacts_enabled: bool = Field(default=True, description="Enable artifact removal")
    artifact_size_threshold: int = Field(default=50, ge=10, le=200, description="Maximum artifact size in pixels")
    
    # Performance settings
    enable_parallel_processing: bool = Field(default=False, description="Enable parallel processing for multiple pages")
    max_concurrent_pages: int = Field(default=4, ge=1, le=16, description="Maximum concurrent pages for parallel processing")
    
    def to_preprocessing_config(self) -> PreprocessingConfig:
        """Convert to PreprocessingConfig object."""
        return PreprocessingConfig(
            deskew_enabled=self.deskew_enabled,
            deskew_threshold=self.deskew_threshold,
            denoise_enabled=self.denoise_enabled,
            denoise_method=self.denoise_method,
            binarize_enabled=self.binarize_enabled,
            binarize_method=self.binarize_method,
            contrast_enabled=self.contrast_enabled,
            contrast_factor=self.contrast_factor,
            sharpen_enabled=self.sharpen_enabled,
            sharpen_factor=self.sharpen_factor,
            crop_margins_enabled=self.crop_margins_enabled,
            margin_threshold=self.margin_threshold,
            scale_enabled=self.scale_enabled,
            target_dpi=self.target_dpi,
            max_scale_factor=self.max_scale_factor,
            remove_artifacts_enabled=self.remove_artifacts_enabled,
            artifact_size_threshold=self.artifact_size_threshold
        )


class PreprocessingConfigManager:
    """Manager for preprocessing configurations."""
    
    @staticmethod
    def get_default_config() -> PreprocessingSettings:
        """Get default preprocessing configuration."""
        return PreprocessingSettings()
    
    @staticmethod
    def get_ocr_optimized_config() -> PreprocessingSettings:
        """Get configuration optimized for OCR accuracy."""
        return PreprocessingSettings(
            deskew_enabled=True,
            deskew_threshold=0.5,
            denoise_enabled=True,
            denoise_method="bilateral",
            binarize_enabled=True,
            binarize_method="otsu",
            contrast_enabled=True,
            contrast_factor=1.2,
            sharpen_enabled=True,
            sharpen_factor=1.5,
            crop_margins_enabled=True,
            margin_threshold=10,
            scale_enabled=True,
            target_dpi=300,
            max_scale_factor=2.0,
            remove_artifacts_enabled=True,
            artifact_size_threshold=50,
            enable_parallel_processing=False,
            max_concurrent_pages=4
        )
    
    @staticmethod
    def get_fast_config() -> PreprocessingSettings:
        """Get configuration optimized for processing speed."""
        return PreprocessingSettings(
            deskew_enabled=False,
            denoise_enabled=True,
            denoise_method="gaussian",
            binarize_enabled=True,
            binarize_method="otsu",
            contrast_enabled=False,
            sharpen_enabled=False,
            crop_margins_enabled=False,
            scale_enabled=True,
            target_dpi=200,
            max_scale_factor=1.5,
            remove_artifacts_enabled=False,
            enable_parallel_processing=True,
            max_concurrent_pages=8
        )
    
    @staticmethod
    def get_high_quality_config() -> PreprocessingSettings:
        """Get configuration optimized for maximum quality."""
        return PreprocessingSettings(
            deskew_enabled=True,
            deskew_threshold=0.2,
            denoise_enabled=True,
            denoise_method="bilateral",
            binarize_enabled=True,
            binarize_method="adaptive",
            contrast_enabled=True,
            contrast_factor=1.5,
            sharpen_enabled=True,
            sharpen_factor=2.0,
            crop_margins_enabled=True,
            margin_threshold=5,
            scale_enabled=True,
            target_dpi=400,
            max_scale_factor=3.0,
            remove_artifacts_enabled=True,
            artifact_size_threshold=30,
            enable_parallel_processing=False,
            max_concurrent_pages=2
        )
    
    @staticmethod
    def get_config_by_name(name: str) -> PreprocessingSettings:
        """Get configuration by name."""
        configs = {
            "default": PreprocessingConfigManager.get_default_config,
            "ocr_optimized": PreprocessingConfigManager.get_ocr_optimized_config,
            "fast": PreprocessingConfigManager.get_fast_config,
            "high_quality": PreprocessingConfigManager.get_high_quality_config
        }
        
        if name not in configs:
            raise ValueError(f"Unknown configuration name: {name}. Available: {list(configs.keys())}")
        
        return configs[name]()
    
    @staticmethod
    def list_available_configs() -> Dict[str, str]:
        """List available configuration presets."""
        return {
            "default": "Balanced configuration with moderate processing",
            "ocr_optimized": "Optimized for OCR accuracy with comprehensive preprocessing",
            "fast": "Optimized for speed with minimal processing",
            "high_quality": "Maximum quality with extensive preprocessing"
        }





