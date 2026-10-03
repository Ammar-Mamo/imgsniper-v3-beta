"""
Utility for getting dimension input from user
"""
# وحدة مساعدة - دوال مشتركة ومساعدة للوحدات الأخرى


import re
from typing import Tuple, Optional
from rich.console import Console
from ...core.i18n.i18n import i18n
from .console_input import ask_line

def get_dimensions_from_user(default_width: int = 300, default_height: int = 300) -> Tuple[int, int]:
    """
    Get minimum dimensions from user with multiple input formats support.
    
    Supported formats:
    - Empty (uses default)
    - Single number: 500 (uses for both width and height)
    - Two numbers: 800 600 or 800x600 or 800,600
    - Explicit format: width=800 height=600
    
    Returns:
        Tuple of (width, height)
    """
    console = Console()
    
    console.print(f"\n[blue]{i18n.get('dimensions.dimension_title')}[/blue]")
    console.print(f"[yellow]{i18n.get('dimensions.dimension_default').format(default_width, default_height)}[/yellow]")
    console.print(f"\n[green]{i18n.get('dimensions.dimension_input_methods')}[/green]")
    console.print(f"  • {i18n.get('dimensions.dimension_empty_default').format(default_width, default_height)}")
    console.print(f"  • {i18n.get('dimensions.dimension_single_number')}")
    console.print(f"  • {i18n.get('dimensions.dimension_two_numbers')}")
    console.print(f"  • {i18n.get('dimensions.dimension_explicit_format')}")
    
    while True:
        try:
            user_input = ask_line(f"\n{i18n.get('dimensions.dimension_input_prompt')}").strip()
            
            # Empty مدخلات - use deعيبs
            if not user_input:
                console.print(f"[green]{i18n.get('dimensions.dimension_using_default').format(default_width, default_height)}[/green]")
                return default_width, default_height
            
            # Try to parse the مدخلات
            width, height = parse_dimension_input(user_input)
            
            if width and height:
                # التحقق من صحة بُعدs
                if width < 1 or height < 1:
                    console.print(f"[red]{i18n.get('dimensions.dimension_invalid_size')}[/red]")
                    continue
                
                if width > 10000 or height > 10000:
                    console.print(f"[red]{i18n.get('dimensions.dimension_too_large')}[/red]")
                    continue
                
                console.print(f"[green]{i18n.get('dimensions.dimension_set_success').format(width, height)}[/green]")
                return width, height
            else:
                console.print(f"[red]{i18n.get('dimensions.dimension_invalid_format')}[/red]")
                
        except KeyboardInterrupt:
            console.print(f"\n[blue]{i18n.get('dimensions.cancelled')}[/blue]")
            return default_width, default_height
        except Exception as e:
            console.print(f"[red]{i18n.get('dimensions.error').format(e)}[/red]")

def parse_dimension_input(user_input: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Parse various dimension input formats.
    
    Returns:
        Tuple of (width, height) or (None, None) if parsing fails
    """
    user_input = user_input.strip().lower()
    
    # تنسيق: عرض=800 ارتفاع=600
    explicit_match = re.search(r'width\s*=\s*(\d+).*height\s*=\s*(\d+)', user_input)
    if explicit_match:
        return int(explicit_match.group(1)), int(explicit_match.group(2))
    
    # تنسيق: ارتفاع=600 عرض=800 (reversed أمر)
    explicit_match_rev = re.search(r'height\s*=\s*(\d+).*width\s*=\s*(\d+)', user_input)
    if explicit_match_rev:
        return int(explicit_match_rev.group(2)), int(explicit_match_rev.group(1))
    
    # إزالة شائع separators and split
    cleaned = re.sub(r'[x,×*]', ' ', user_input)
    numbers = re.findall(r'\d+', cleaned)
    
    if len(numbers) == 1:
        # Single رقم - use for both بُعدs
        dim = int(numbers[0])
        return dim, dim
    elif len(numbers) == 2:
        # Two رقمs - عرض and ارتفاع
        return int(numbers[0]), int(numbers[1])
    elif len(numbers) > 2:
        # More than 2 رقمs - use أول two
        return int(numbers[0]), int(numbers[1])
    
    return None, None

def validate_dimensions(width: int, height: int) -> bool:
    """Validate that dimensions are reasonable."""
    return (1 <= width <= 10000) and (1 <= height <= 10000)

# Test وظيفة
if __name__ == "__main__":
    print(i18n.get('dimensions.testing_dimension_parser'))
    
    test_cases = [
        "",
        "500",
        "800 600",
        "800x600",
        "800,600",
        "800×600",
        "width=800 height=600",
        "height=600 width=800",
        "1920x1080",
        "300",
        "invalid input",
        "800 600 400",  # More than 2 numbers
    ]
    
    for test_input in test_cases:
        result = parse_dimension_input(test_input)
        print(f"Input: '{test_input}' → {result}")