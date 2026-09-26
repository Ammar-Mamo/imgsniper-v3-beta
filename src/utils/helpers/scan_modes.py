"""
Scan mode management for different performance levels
إدارة وضعيات الفحص لمستويات أداء مختلفة
"""
# وحدة مساعدة - دوال مشتركة ومساعدة للوحدات الأخرى


import os
import psutil
from typing import Dict, Any
from ...core.config import config

class ScanModeManager:
    """Manages different scanning modes for optimal performance."""
    
    def __init__(self):
        self.cpu_count = os.cpu_count() or 4
        self.total_ram = psutil.virtual_memory().total / (1024**3)  # GB
        
        # Define scan وضعs
        self.modes = {
            'normal': {
                'name': 'Normal',
                'max_workers': min(2, self.cpu_count),
                'batch_size': 500,
                'memory_limit_mb': 1024,
                'enable_caching': False,
                'parallel_io': False,
                'chunk_size': 4096,
                'use_process_pool': False,
                'cpu_usage': 'Low (25%)',
                'ram_usage': 'Low (1GB)',
                'performance': 'Standard'
            },
            'medium': {
                'name': 'Medium',
                'max_workers': min(max(4, self.cpu_count // 2), self.cpu_count),
                'batch_size': 1000,
                'memory_limit_mb': 2048,
                'enable_caching': True,
                'parallel_io': True,
                'chunk_size': 8192,
                'use_process_pool': True,  # Enable multi-process for better CPU utilization
                'cpu_usage': 'Medium (50%)',
                'ram_usage': 'Medium (2GB)',
                'performance': 'Balanced + Multi-Process'
            },
            'advanced': {
                'name': 'Advanced',
                'max_workers': min(max(6, int(self.cpu_count * 0.75)), self.cpu_count),
                'batch_size': 2000,
                'memory_limit_mb': 4096,
                'enable_caching': True,
                'parallel_io': True,
                'chunk_size': 16384,
                'use_process_pool': True,
                'cpu_usage': 'High (75%)',
                'ram_usage': 'High (4GB)',
                'performance': 'Fast + Multi-Process'
            },
            'ultra': {
                'name': 'Ultra',
                'max_workers': max(min(self.cpu_count * 2, 16), self.cpu_count),  # Up to 2x CPU cores but max 16
                'batch_size': 3000,  # Reduced for better memory management
                'memory_limit_mb': min(8192, int(self.total_ram * 1024 * 0.8)),
                'enable_caching': True,
                'parallel_io': True,
                'chunk_size': 32768,
                'use_process_pool': True,
                'cpu_usage': 'Maximum (100%)',
                'ram_usage': f'Maximum ({min(8, int(self.total_ram * 0.8))}GB)',
                'performance': 'Ultra Fast + Multi-Process'
            }
        }
        
        # Current وضع
        self.current_mode = config.get('processing.scan_mode', 'medium')
    
    def get_mode_config(self, mode: str = None) -> Dict[str, Any]:
        """Get configuration for specified mode."""
        if mode is None:
            # Alطريقةs get the laاختبار وضع from إعدادات
            mode = config.get('processing.scan_mode', 'medium')
            self.current_mode = mode
        
        return self.modes.get(mode, self.modes['medium'])
    
    def set_mode(self, mode: str) -> bool:
        """Set the current scan mode."""
        if mode in self.modes:
            self.current_mode = mode
            
            # تحديث إعدادات with جديد وضع إعدادات
            mode_config = self.modes[mode]
            config.set('processing.scan_mode', mode)
            config.set('processing.max_workers', mode_config['max_workers'])
            config.set('processing.batch_size', mode_config['batch_size'])
            config.set('processing.memory_limit_mb', mode_config['memory_limit_mb'])
            config.set('processing.enable_caching', mode_config['enable_caching'])
            config.set('processing.parallel_io', mode_config['parallel_io'])
            config.set('processing.chunk_size', mode_config['chunk_size'])
            config.set('processing.use_process_pool', mode_config['use_process_pool'])
            

            
            return True
        return False
    
    def get_available_modes(self) -> Dict[str, Dict[str, Any]]:
        """Get all available scan modes."""
        return self.modes
    
    def get_system_info(self, quick: bool = False) -> Dict[str, Any]:
        """Get current system information.
        
        Args:
            quick: If True, use cached CPU value to avoid delay
        """
        memory = psutil.virtual_memory()
        if quick:
            # Use non-blocking CPU reading for حقيقي-وقت upتاريخs
            cpu_percent = psutil.cpu_percent(interval=None)
        else:
            cpu_percent = psutil.cpu_percent(interval=1)
        
        return {
            'cpu_count': self.cpu_count,
            'cpu_usage': f"{cpu_percent:.1f}%",
            'total_ram_gb': f"{self.total_ram:.1f}GB",
            'available_ram_gb': f"{memory.available / (1024**3):.1f}GB",
            'ram_usage': f"{memory.percent:.1f}%"
        }
    
    def recommend_mode(self) -> str:
        """Recommend optimal mode based on system specs."""
        if self.total_ram >= 16 and self.cpu_count >= 8:
            return 'ultra'
        elif self.total_ram >= 8 and self.cpu_count >= 6:
            return 'advanced'
        elif self.total_ram >= 4 and self.cpu_count >= 4:
            return 'medium'
        else:
            return 'normal'
    
    def validate_mode_for_system(self, mode: str) -> bool:
        """Check if the system can handle the specified mode."""
        mode_config = self.modes.get(mode)
        if not mode_config:
            return False
        
        # فحص RAM متطلبs
        required_ram_gb = mode_config['memory_limit_mb'] / 1024
        if required_ram_gb > self.total_ram * 0.9:  # Don't use more than 90% of RAM
            return False
        
        # فحص CPU متطلبs
        if mode_config['max_workers'] > self.cpu_count * 2:  # Don't exceed 2x CPU جوهريs
            return False
        
        return True

# Global مثيل
scan_mode_manager = ScanModeManager()