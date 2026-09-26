"""
Internationalization manager for ImgSniper
"""
# وحدة الترجمة - يدير النصوص متعددة اللغات


from typing import Dict, Any
from .translations_english import ENGLISH_TRANSLATIONS
from .translations_arabic import ARABIC_TRANSLATIONS


class I18nManager:
    """Internationalization manager."""
    
    def __init__(self):
        self.translations = {
            "en": ENGLISH_TRANSLATIONS,
            "ar": ARABIC_TRANSLATIONS
        }
        self.current_language = "ar"
    
    def set_language(self, language: str):
        """Set the current language."""
        if language in self.translations:
            self.current_language = language
    
    def get(self, key: str, **kwargs) -> str:
        """Get translated text by key."""
        keys = key.split('.')
        value = self.translations.get(self.current_language, {})
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                # العودة للإنجليزية إذا لم يتم العثور على المفتاح
                value = self.translations.get("en", {})
                for k in keys:
                    if isinstance(value, dict) and k in value:
                        value = value[k]
                    else:
                        return f"[Missing: {key}]"
                break
        
        if isinstance(value, str) and kwargs:
            try:
                return value.format(**kwargs)
            except (KeyError, ValueError):
                return value
                
        return value if isinstance(value, str) else f"[Invalid: {key}]"
    
    def get_available_languages(self) -> Dict[str, str]:
        """Get available languages."""
        return {
            "en": "English",
            "ar": "عربي"
        }
    
    def get_current_language(self) -> str:
        """Get current language code."""
        return self.current_language