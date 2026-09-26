"""
Internationalization support for ImgSniper - Main interface
"""
# وحدة الترجمة - يدير النصوص متعددة اللغات


from .i18n_manager import I18nManager

# مثيل الترجمة العام
i18n = I18nManager()

def get_text(key: str, **kwargs) -> str:
    """دالة مساعدة للحصول على النص المترجم."""
    # جرب القسم الشائع أولاً، ثم جرب المفتاح مباشرة
    result = i18n.get(f"common.{key}", **kwargs)
    if result.startswith("[Missing:"):
        result = i18n.get(key, **kwargs)
    return result