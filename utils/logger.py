"""
Comprehensive logging utility for Clark Bot with colored console output.
"""

import logging
import os
import sys
from datetime import datetime
from typing import Optional


class ColoredFormatter(logging.Formatter):
    """Custom formatter with ANSI colors for console output."""
    
    # ANSI color codes
    COLORS = {
        'RESET': '\033[0m',
        'BOLD': '\033[1m',
        'DIM': '\033[2m',
        'RED': '\033[91m',
        'GREEN': '\033[92m',
        'YELLOW': '\033[93m',
        'BLUE': '\033[94m',
        'MAGENTA': '\033[95m',
        'CYAN': '\033[96m',
        'WHITE': '\033[97m',
        'BG_RED': '\033[41m',
        'BG_GREEN': '\033[42m',
        'BG_YELLOW': '\033[43m',
        'BG_BLUE': '\033[44m',
    }
    
    # Level-specific colors and icons
    LEVEL_STYLES = {
        logging.DEBUG: {
            'color': 'CYAN',
            'icon': '◆',
            'bg': None
        },
        logging.INFO: {
            'color': 'GREEN',
            'icon': '✓',
            'bg': None
        },
        logging.WARNING: {
            'color': 'YELLOW',
            'icon': '⚠',
            'bg': 'BG_YELLOW'
        },
        logging.ERROR: {
            'color': 'RED',
            'icon': '✗',
            'bg': None
        },
        logging.CRITICAL: {
            'color': 'WHITE',
            'icon': '☠',
            'bg': 'BG_RED'
        }
    }
    
    # Category colors for different components
    CATEGORY_COLORS = {
        'BOT': 'BLUE',
        'DATABASE': 'MAGENTA',
        'DISCORD': 'CYAN',
        'COGS': 'GREEN',
        'COMMANDS': 'YELLOW',
        'EVENTS': 'BLUE',
        'AI': 'MAGENTA',
        'ECONOMY': 'GREEN',
        'MODERATION': 'RED',
        'LEVELING': 'CYAN',
        'MUSIC': 'GREEN',
        'CACHE': 'YELLOW',
        'HTTP': 'BLUE',
        'DEFAULT': 'WHITE'
    }
    
    def __init__(self, use_colors: bool = True, show_timestamp: bool = True):
        super().__init__()
        self.use_colors = use_colors and (sys.platform != 'win32' or 'ANSICON' in os.environ)
        self.show_timestamp = show_timestamp
        
    def format(self, record: logging.LogRecord) -> str:
        # Get level style
        level_style = self.LEVEL_STYLES.get(record.levelno, self.LEVEL_STYLES[logging.INFO])
        
        # Extract category from logger name
        category = self._extract_category(record.name)
        category_color = self.CATEGORY_COLORS.get(category, self.CATEGORY_COLORS['DEFAULT'])
        
        # Build timestamp
        timestamp = ""
        if self.show_timestamp:
            time_str = datetime.fromtimestamp(record.created).strftime('%H:%M:%S.%f')[:-3]
            if self.use_colors:
                timestamp = f"{self.COLORS['DIM']}[{time_str}]{self.COLORS['RESET']} "
            else:
                timestamp = f"[{time_str}] "
        
        # Build level indicator
        if self.use_colors:
            level_color = self.COLORS[level_style['color']]
            icon = level_style['icon']
            level_name = record.levelname[:4].center(4)
            
            if level_style['bg']:
                level_indicator = f"{self.COLORS[level_style['bg']]}{self.COLORS['BOLD']} {icon} {level_name} {self.COLORS['RESET']}"
            else:
                level_indicator = f"{level_color}{self.COLORS['BOLD']}{icon}{self.COLORS['RESET']} {level_color}{level_name}{self.COLORS['RESET']}"
            
            # Build category tag
            cat_color = self.COLORS[category_color]
            category_tag = f"{cat_color}[{category:12}]{self.COLORS['RESET']}"
        else:
            icon = level_style['icon']
            level_indicator = f"{icon} {record.levelname[:4].center(4)}"
            category_tag = f"[{category:12}]"
        
        # Build message
        message = record.getMessage()
        
        # Format the final output
        formatted = f"{timestamp}{level_indicator} {category_tag} {message}"
        
        # Add exception info if present
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            if self.use_colors:
                formatted += f"\n{self.COLORS['RED']}{exc_text}{self.COLORS['RESET']}"
            else:
                formatted += f"\n{exc_text}"
        
        return formatted
    
    def _extract_category(self, name: str) -> str:
        """Extract category from logger name."""
        name_upper = name.upper()
        if 'CLARK' in name_upper or name == '__main__':
            return 'BOT'
        elif 'DATABASE' in name_upper or 'DB_POOL' in name_upper or 'MYSQL' in name_upper:
            return 'DATABASE'
        elif 'DISCORD' in name_upper:
            return 'DISCORD'
        elif 'COG' in name_upper:
            # Extract cog name
            parts = name.split('.')
            if len(parts) > 1:
                cog_name = parts[-1].replace('_', '').upper()
                if 'ECONOMY' in cog_name:
                    return 'ECONOMY'
                elif 'MODERATION' in cog_name or 'MOD' in cog_name:
                    return 'MODERATION'
                elif 'LEVEL' in cog_name:
                    return 'LEVELING'
                elif 'MUSIC' in cog_name:
                    return 'MUSIC'
                elif 'AI' in cog_name:
                    return 'AI'
                return cog_name[:12]
            return 'COGS'
        elif 'COMMAND' in name_upper:
            return 'COMMANDS'
        elif 'EVENT' in name_upper:
            return 'EVENTS'
        elif 'CACHE' in name_upper:
            return 'CACHE'
        elif 'HTTP' in name_upper or 'AIOHTTP' in name_upper:
            return 'HTTP'
        return 'DEFAULT'


class BotLogger:
    """Centralized logging manager for the bot."""
    
    _instance: Optional['BotLogger'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, level: int = logging.INFO, log_file: Optional[str] = None):
        if BotLogger._initialized:
            return
            
        self.logger = logging.getLogger('clark')
        self.logger.setLevel(level)
        self.logger.propagate = False
        
        # Clear existing handlers
        self.logger.handlers.clear()
        
        # Console handler with colors
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_formatter = ColoredFormatter(use_colors=True, show_timestamp=True)
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # File handler (no colors)
        if log_file:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(level)
            file_formatter = logging.Formatter(
                '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
        
        BotLogger._initialized = True
        self.info("Logging system initialized", 'BOT')
    
    def get_logger(self, name: str) -> logging.Logger:
        """Get a named logger."""
        return logging.getLogger(f'clark.{name}')
    
    def debug(self, message: str, category: str = 'DEFAULT'):
        """Log debug message."""
        self.logger.debug(f"[{category:12}] {message}")
    
    def info(self, message: str, category: str = 'DEFAULT'):
        """Log info message."""
        self.logger.info(f"[{category:12}] {message}")
    
    def warning(self, message: str, category: str = 'DEFAULT'):
        """Log warning message."""
        self.logger.warning(f"[{category:12}] {message}")
    
    def error(self, message: str, category: str = 'DEFAULT', exc_info: bool = False):
        """Log error message."""
        self.logger.error(f"[{category:12}] {message}", exc_info=exc_info)
    
    def critical(self, message: str, category: str = 'DEFAULT', exc_info: bool = False):
        """Log critical message."""
        self.logger.critical(f"[{category:12}] {message}", exc_info=exc_info)
    
    def success(self, message: str, category: str = 'DEFAULT'):
        """Log success message (custom level)."""
        # Use info level but with success formatting handled by formatter
        self.logger.info(f"[{category:12}] ✓ {message}")
    
    def command(self, user: str, command: str, guild: Optional[str] = None):
        """Log command usage."""
        guild_str = f" in {guild}" if guild else ""
        self.logger.info(f"[{'COMMANDS':12}] {user} used /{command}{guild_str}")
    
    def database(self, operation: str, details: str = ""):
        """Log database operations."""
        detail_str = f" | {details}" if details else ""
        self.logger.debug(f"[{'DATABASE':12}] {operation}{detail_str}")
    
    def cache(self, operation: str, hit: bool = True, details: str = ""):
        """Log cache operations."""
        status = "HIT" if hit else "MISS"
        detail_str = f" | {details}" if details else ""
        self.logger.debug(f"[{'CACHE':12}] {operation} [{status}]{detail_str}")
    
    def guild_event(self, event_type: str, guild_name: str, guild_id: int, extra: str = ""):
        """Log guild join/remove events."""
        extra_str = f" | {extra}" if extra else ""
        self.logger.info(f"[{'EVENTS':12}] {event_type}: {guild_name} (ID: {guild_id}){extra_str}")


# Global logger instance
logger = BotLogger()

# Convenience function to get logger
def get_logger(name: str) -> logging.Logger:
    """Get a named logger."""
    return logger.get_logger(name)
