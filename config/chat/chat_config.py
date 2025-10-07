import os


class ChatConfig:
    """
    Configuration for chat functionality and modes.
    
    Environment Variables:
    - CHAT_MODE: 'query_only' or 'with_history' (default: 'query_only')
    - MAX_HISTORY_LENGTH: Maximum history messages when history enabled (default: 10)
    
    Examples:
    - Query-only mode: CHAT_MODE=query_only
    - History mode: CHAT_MODE=with_history
    """
    
    @staticmethod
    def CHAT_MODE():
        """
        Chat mode configuration.
        Options: 'query_only' or 'with_history'
        """
        return os.getenv("CHAT_MODE", "query_only")
    
    @staticmethod
    def ENABLE_HISTORY():
        """
        Whether to enable chat history functionality.
        Returns True if CHAT_MODE is 'with_history', False otherwise.
        """
        return ChatConfig.CHAT_MODE().lower() == "with_history"
    
    @staticmethod
    def MAX_HISTORY_LENGTH():
        """
        Maximum number of history messages to keep when history is enabled.
        """
        return int(os.getenv("MAX_HISTORY_LENGTH", "10"))
