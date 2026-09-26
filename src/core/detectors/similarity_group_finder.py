"""
Similar image group finding functionality
"""
# وحدة كشف وتحليل الصور - يحتوي على خوارزميات البحث والفحص


import logging
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
import imagehash
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

from ...core.config import config
from ..i18n.i18n import i18n
from ...utils.helpers.scan_modes import scan_mode_manager


def _compare_hash_batch_worker(args: tuple) -> List[tuple]:
    """Worker function for comparing hash batches in parallel."""
    batch_items, all_items, threshold, start_idx = args
    matches = []
    
    # معالجة batch عنصرs efficiently
    for i, (img1, hash1) in enumerate(batch_items):
        actual_idx = start_idx + i
        # Only check عنصرs that come after this واحد in the مملوء قائمة
        for j in range(actual_idx + 1, len(all_items)):
            img2, hash2 = all_items[j]
            try:
                # Fast hash comparison - this is CPU intensive and will utilize عمليةor
                hash_diff = hash1 - hash2
                if hash_diff <= threshold:
                    matches.append((img1, img2))
                    
                # Early إنهاء تحسين for very different hashes
                if hash_diff > threshold * 3:
                    # Skip similar comparisons in this batch for أداء
                    continue
            except Exception:
                continue
    
    return matches


class SimilarityGroupFinder:
    """Find groups of similar images based on hash comparison."""
    
    def __init__(self):
        pass
    

    # The hash_size that processing.phash_threshold refers to. Normal mode
    # uses 8, which is also imagehash's own default.
    REFERENCE_HASH_SIZE = 8

    @classmethod
    def _detect_hash_size(cls, image_hashes) -> int:
        """
        Read the real hash_size off the hash objects themselves.

        Deriving it from the data keeps this correct without threading a
        new parameter through every caller, and it cannot drift out of
        sync with the hash_size the calculator actually used.
        """
        for h in image_hashes.values():
            try:
                size = int(h.hash.shape[0])
                if size > 0:
                    return size
            except (AttributeError, IndexError, TypeError, ValueError):
                pass
            break
        return cls.REFERENCE_HASH_SIZE

    @classmethod
    def _scale_threshold(cls, base_threshold: int, hash_size: int) -> int:
        """
        Rescale a reference-size threshold so its ratio is mode independent.

        5 at hash_size 8 -> 5 / 8 / 11 / 20 for hash sizes 8 / 10 / 12 / 16,
        i.e. a constant ~92% similarity in every scan mode.
        """
        ref = cls.REFERENCE_HASH_SIZE
        if hash_size <= 0 or hash_size == ref:
            return base_threshold
        scaled = base_threshold * (hash_size * hash_size) / float(ref * ref)
        return max(1, int(round(scaled)))

    def _resolve_threshold(self, image_hashes) -> int:
        """Turn processing.phash_threshold into the effective Hamming distance."""
        threshold_config = config.get('processing.phash_threshold', 5)
        try:
            base = int(threshold_config)
        except (TypeError, ValueError):
            base = 5
        base = max(1, base)
        return self._scale_threshold(base, self._detect_hash_size(image_hashes))
    def find_similar_groups(self, image_hashes: Dict[str, imagehash.ImageHash], console: Optional[Console] = None) -> List[List[str]]:
        """Find groups of similar images based on hash distance with optimized parallel algorithm."""
        # Audit finding P0-4: the configured threshold is a raw Hamming
        # distance, but its MEANING depends on hash_size, which varies by
        # scan mode (Normal=8, Medium=10, Advanced=12, Ultra=16). The
        # maximum possible distance is hash_size**2, so a fixed 5 meant
        # 92.2% similarity in Normal mode but 98.0% in Ultra mode:
        # raising the scan precision silently made matching far stricter
        # and returned FEWER groups, the opposite of what a user expects
        # when they select a more thorough mode.
        #
        # The configured value is therefore read as the distance at the
        # REFERENCE hash size (8 = Normal mode, also imagehash's own
        # default) and rescaled so the similarity ratio is identical in
        # every mode. Normal mode behaviour is unchanged.
        threshold = self._resolve_threshold(image_hashes)
        
        # تحويل to قائمة for faster iteنسبةn and ensure consistent أمرing
        hash_items = sorted(list(image_hashes.items()), key=lambda x: x[0])  # ترتيب by مسار for consistency
        total_items = len(hash_items)
        
        if total_items < 2:
            return []
        
        # جلب scan وضع إعداداتuنسبةn for parجميعel عمليةing
        mode_config = scan_mode_manager.get_mode_config()
        max_workers = mode_config['max_workers']
        batch_size = mode_config['batch_size']
        use_process_pool = mode_config.get('use_process_pool', False)
        
        # For smجميع بياناتمجموعةs, use واحد-خيطed منهج to avoid overhead
        if total_items < 500:
            return self._find_similar_groups_sequential(hash_items, threshold, console)
        
        # For Normal وضع with وضعrate بياناتمجموعةs, use حدed parجميعel عمليةing
        if mode_config['name'] == 'Normal' and total_items < 2000:
            return self._find_similar_groups_sequential(hash_items, threshold, console)
        
        # Use parجميعel عمليةing for larger بياناتمجموعةs
        executor_class = ProcessPoolExecutor if use_process_pool else ThreadPoolExecutor
        
        # Adjust batch حجم based on بياناتمجموعة حجم and وضع
        if mode_config['name'] == 'Ultra':
            dynamic_batch_size = max(50, min(500, total_items // (max_workers * 4)))
        elif mode_config['name'] == 'Advanced':
            dynamic_batch_size = max(100, min(1000, total_items // (max_workers * 2)))
        else:  # Medium
            dynamic_batch_size = max(200, min(1500, total_items // max_workers))
        
        all_matches = []
        
        if console:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                console=console
            ) as progress:
                
                # Use إجمالي عنصرs for تقدم مسارing instead of batches
                task = progress.add_task(i18n.get('common.comparing_images'), total=total_items)
                
                try:
                    with executor_class(max_workers=max_workers) as executor:
                        # إنشاء batches for parجميعel عمليةing with ذاكرة إدارة
                        futures = []
                        processed_count = 0
                        
                        # معالجة in smجميعer chunks to prحدث ذاكرة overfمنخفض
                        chunk_limit = max_workers * 2  # Limit conحالي futures
                        
                        for i in range(0, total_items, dynamic_batch_size):
                            batch_items = hash_items[i:i + dynamic_batch_size]
                            start_idx = i
                            current_batch_size = len(batch_items)
                            
                            # Wait for some futures to كامل if we have too many
                            while len(futures) >= chunk_limit:
                                completed_futures = [f for f in futures if f.done()]
                                for future in completed_futures:
                                    try:
                                        matches = future.result()
                                        all_matches.extend(matches)
                                        futures.remove(future)
                                        # تحديث تقدم based on فعلي batch حجم
                                        batch_size = getattr(future, '_batch_size', dynamic_batch_size)
                                        progress.advance(task, batch_size)
                                        processed_count += batch_size
                                    except Exception as e:
                                        logging.warning(f"Error processing batch: {e}")
                                        futures.remove(future)
                                        batch_size = getattr(future, '_batch_size', dynamic_batch_size)
                                        progress.advance(task, batch_size)
                                        processed_count += batch_size
                                
                                # If no futures كاملd, wait for واحد
                                if len(futures) >= chunk_limit:
                                    completed = next(as_completed(futures[:1]))
                                    try:
                                        matches = completed.result()
                                        all_matches.extend(matches)
                                        futures.remove(completed)
                                        batch_size = getattr(completed, '_batch_size', dynamic_batch_size)
                                        progress.advance(task, batch_size)
                                        processed_count += batch_size
                                    except Exception as e:
                                        logging.warning(f"Error processing completed future: {e}")
                                        futures.remove(completed)
                                        batch_size = getattr(completed, '_batch_size', dynamic_batch_size)
                                        progress.advance(task, batch_size)
                                        processed_count += batch_size
                            
                            future = executor.submit(_compare_hash_batch_worker, (batch_items, hash_items, threshold, start_idx))
                            # Store batch حجم for later use using setattr to avoid type issues
                            setattr(future, '_batch_size', current_batch_size)
                            futures.append(future)
                        
                        # Collect reرئيسيing نتائج
                        for future in as_completed(futures):
                            try:
                                matches = future.result()
                                all_matches.extend(matches)
                                batch_size = getattr(future, '_batch_size', dynamic_batch_size)
                                progress.advance(task, batch_size)
                                processed_count += batch_size
                            except Exception:
                                batch_size = getattr(future, '_batch_size', dynamic_batch_size)
                                progress.advance(task, batch_size)
                                processed_count += batch_size
                            
                except Exception as e:
                    # Fجميعback to sequential عمليةing
                    if console:
                        console.print(f"[yellow]⚠️ Parallel processing failed, falling back to sequential: {e}[/yellow]")
                    return self._find_similar_groups_sequential(hash_items, threshold, console)
        else:
            # معالجة without تقدم bar
            try:
                with executor_class(max_workers=max_workers) as executor:
                    futures = []
                    chunk_limit = max_workers * 2
                    
                    for i in range(0, total_items, dynamic_batch_size):
                        batch_items = hash_items[i:i + dynamic_batch_size]
                        start_idx = i
                        
                        # Memory إدارة for futures
                        while len(futures) >= chunk_limit:
                            completed_futures = [f for f in futures if f.done()]
                            for future in completed_futures:
                                try:
                                    matches = future.result()
                                    all_matches.extend(matches)
                                    futures.remove(future)
                                except Exception:
                                    futures.remove(future)
                            
                            if len(futures) >= chunk_limit:
                                completed = next(as_completed(futures[:1]))
                                try:
                                    matches = completed.result()
                                    all_matches.extend(matches)
                                    futures.remove(completed)
                                except Exception:
                                    futures.remove(completed)
                        
                        future = executor.submit(_compare_hash_batch_worker, (batch_items, hash_items, threshold, start_idx))
                        futures.append(future)
                    
                    for future in as_completed(futures):
                        try:
                            matches = future.result()
                            all_matches.extend(matches)
                        except Exception as e:
                            # Audit P2-20: was a silent "pass". A failed batch
                            # discards EVERY match that batch would have
                            # produced, so whole groups quietly vanish from the
                            # report. The two sibling failure paths in this
                            # module already log at WARNING; this is the same
                            # class of failure and now behaves like them.
                            logging.warning(f"Error collecting batch results: {e}")
            except Exception:
                return self._find_similar_groups_sequential(hash_items, threshold, console)
        
        # بناء groups from matches using Union-Find خوارزمية for كفاءة
        return self._build_groups_from_matches(all_matches, hash_items)
    
    def _find_similar_groups_sequential(self, hash_items: List[tuple], threshold: int, console: Optional[Console] = None) -> List[List[str]]:
        """
        Sequential method for finding similar groups.

        Collects ALL pairwise matches within the threshold and then builds
        groups with the SAME Union-Find algorithm used by the parallel path.
        This guarantees IDENTICAL results regardless of image count or scan
        mode (transitive grouping), fixing the previous inconsistency where
        small datasets used a greedy algorithm and large ones used Union-Find.
        """
        all_matches = []
        total_items = len(hash_items)

        if console and total_items > 0:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                console=console
            ) as progress:
                task = progress.add_task(i18n.get('common.comparing_images'), total=total_items)

                for i, (img1, hash1) in enumerate(hash_items):
                    # Compare against all remaining items to collect every match
                    for j in range(i + 1, total_items):
                        img2, hash2 = hash_items[j]
                        try:
                            if hash1 - hash2 <= threshold:
                                all_matches.append((img1, img2))
                        except Exception:
                            continue  # Skip invalid hash comparisons
                    progress.advance(task)
        else:
            # Fallback without progress bar
            for i, (img1, hash1) in enumerate(hash_items):
                for j in range(i + 1, total_items):
                    img2, hash2 = hash_items[j]
                    try:
                        if hash1 - hash2 <= threshold:
                            all_matches.append((img1, img2))
                    except Exception:
                        continue  # Skip invalid hash comparisons

        # Use the SAME Union-Find grouping as the parallel path for consistency
        return self._build_groups_from_matches(all_matches, hash_items)
    
    def _build_groups_from_matches(self, matches: List[tuple], hash_items: List[tuple]) -> List[List[str]]:
        """Build similarity groups from matches using Union-Find algorithm."""
        # إنشاء a خريطةping from صورة مسار to فهرس
        path_to_idx = {path: i for i, (path, _) in enumerate(hash_items)}
        
        # Union-Find بيانات هيكل
        parent = list(range(len(hash_items)))
        
        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
        
        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py
        
        # معالجة جميع matches
        for img1, img2 in matches:
            if img1 in path_to_idx and img2 in path_to_idx:
                union(path_to_idx[img1], path_to_idx[img2])
        
        # Group صورةs by their root parent
        groups = {}
        for i, (path, _) in enumerate(hash_items):
            root = find(i)
            if root not in groups:
                groups[root] = []
            groups[root].append(path)
        
        # Return only groups with more than واحد صورة
        return [group for group in groups.values() if len(group) > 1]