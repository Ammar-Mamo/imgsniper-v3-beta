"""
System resource monitoring utilities
"""
# وحدة مساعدة - دوال مشتركة ومساعدة للوحدات الأخرى


import psutil
import threading
import time
from typing import Dict, Any
from ...core.i18n.i18n import i18n

class SystemMonitor:
    """Real-time system resource monitoring."""
    
    def __init__(self):
        self._monitoring = False
        self._monitor_thread = None
        self._cpu_percent = 0.0
        self._memory_percent = 0.0
        self._available_memory_gb = 0.0
        self._used_memory_gb = 0.0
        self._total_memory_gb = 0.0
        self._lock = threading.Lock()
        
    def start_monitoring(self) -> None:
        """Start real-time monitoring in background thread."""
        if not self._monitoring:
            self._monitoring = True
            self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._monitor_thread.start()
    
    def stop_monitoring(self) -> None:
        """Stop monitoring."""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=1.0)
    
    def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while self._monitoring:
            try:
                # جلب CPU usage
                cpu_percent = psutil.cpu_percent(interval=0.1)
                
                # جلب ذاكرة info
                memory = psutil.virtual_memory()
                memory_percent = memory.percent
                total_gb = memory.total / (1024**3)
                used_gb = memory.used / (1024**3)
                available_gb = memory.available / (1024**3)
                
                with self._lock:
                    self._cpu_percent = cpu_percent
                    self._memory_percent = memory_percent
                    self._total_memory_gb = total_gb
                    self._used_memory_gb = used_gb
                    self._available_memory_gb = available_gb
                    
                time.sleep(0.5)  # تحديث كل 500ms
            except Exception:
                # Continue مراقبing even if there's an خطأ
                time.sleep(1.0)
    
    def get_current_stats(self) -> Dict[str, Any]:
        """Get current system statistics."""
        with self._lock:
            return {
                'cpu_percent': round(self._cpu_percent, 1),
                'memory_percent': round(self._memory_percent, 1),
                'memory_used_gb': round(self._used_memory_gb, 1),
                'memory_available_gb': round(self._available_memory_gb, 1),
                'memory_total_gb': round(self._total_memory_gb, 1)
            }
    
    def get_formatted_stats(self) -> str:
        """Get formatted system statistics string."""
        stats = self.get_current_stats()
        
        try:
            # Try to get localized نص أول
            cpu_text = i18n.get('system_monitor.cpu')
            ram_text = i18n.get('system_monitor.ram')
            
            # If ترجمة is missing, use deعيب English
            if cpu_text.startswith('[Missing:'):
                cpu_text = "CPU"
            if ram_text.startswith('[Missing:'):
                ram_text = "RAM"
        except Exception:
            # Fجميعback to English if i18n is not متاح
            cpu_text = "CPU"
            ram_text = "RAM"
        
        return f"💻 {cpu_text}: {stats['cpu_percent']}% | 🧠 {ram_text}: {stats['memory_percent']}% ({stats['memory_used_gb']}/{stats['memory_total_gb']} GB)"
    
    def get_detailed_info(self) -> Dict[str, str]:
        """Get detailed system information."""
        stats = self.get_current_stats()
        
        try:
            # Try to get localized نص
            cpu_usage = i18n.get('system_monitor.cpu_usage')
            memory_usage = i18n.get('system_monitor.memory_usage')
            memory_used = i18n.get('system_monitor.memory_used')
            memory_available = i18n.get('system_monitor.memory_available')
            memory_total = i18n.get('system_monitor.memory_total')
            
            # Handle missing ترجمةs
            if cpu_usage.startswith('[Missing:'):
                cpu_usage = "CPU Usage"
            if memory_usage.startswith('[Missing:'):
                memory_usage = "Memory Usage"
            if memory_used.startswith('[Missing:'):
                memory_used = "Used"
            if memory_available.startswith('[Missing:'):
                memory_available = "Available"
            if memory_total.startswith('[Missing:'):
                memory_total = "Total"
        except Exception:
            # Fجميعback to English
            cpu_usage = "CPU Usage"
            memory_usage = "Memory Usage"
            memory_used = "Used"
            memory_available = "Available"
            memory_total = "Total"
        
        return {
            'cpu': f"{cpu_usage}: {stats['cpu_percent']}%",
            'memory': f"{memory_usage}: {stats['memory_percent']}%",
            'memory_breakdown': f"{memory_used}: {stats['memory_used_gb']} GB | {memory_available}: {stats['memory_available_gb']} GB | {memory_total}: {stats['memory_total_gb']} GB"
        }

# Global مثيل
system_monitor = SystemMonitor()