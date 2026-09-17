"""Responsive Hybrid preflight and explicit primesieve handoff."""
import queue
import threading
from tkinter import messagebox

from prime_sieve.hybrid_policy import MAX_TARGET, parameters


class HybridControls:
    def _hybrid_async(self, work, complete):
        results = queue.Queue()

        def worker():
            try:
                results.put((work(), None))
            except Exception as exc:
                results.put((None, str(exc)))

        def poll():
            if not self.winfo_exists():
                return
            try:
                result, error = results.get_nowait()
            except queue.Empty:
                self.after(80, poll)
                return
            complete(result, error)

        threading.Thread(target=worker, daemon=True).start()
        self.after(80, poll)

    def _schedule_hybrid_preview(self, *_args):
        self._hybrid_preview_version = getattr(self, '_hybrid_preview_version', 0) + 1
        if getattr(self, '_hybrid_preview_after', None):
            self.after_cancel(self._hybrid_preview_after)
        self._hybrid_preview_after = self.after(350, self._refresh_hybrid_preview)

    def _refresh_hybrid_preview(self):
        self._hybrid_preview_after = None
        version = self._hybrid_preview_version
        try:
            main = int(self.quick_hybrid_main_cap_var.get())
            count = int(self.quick_hybrid_filter_prime_count_var.get())
        except ValueError:
            self.quick_hybrid_range_var.set(self.T("quick.hybrid_error_enter_valid_numbers"))
            return
        self.quick_hybrid_range_var.set(self.T("quick.hybrid_range_calculating"))

        def done(result, error):
            if version != self._hybrid_preview_version:
                return
            if error:
                self.quick_hybrid_range_var.set(error)
                return
            text = self.T("quick.hybrid_range_summary", limit=result['limit'],
                           main_max=result['main_max'], max_target=MAX_TARGET)
            try:
                _, end = self._hybrid_selected_range()
                text += self.T("quick.hybrid_range_start_hint")
                if end - 1 > MAX_TARGET:
                    text = text.rsplit(' | ', 1)[0] + self.T("quick.hybrid_range_needs_primesieve")
            except (ValueError, TypeError):
                pass
            self.quick_hybrid_range_var.set(text)

        self._hybrid_async(lambda: parameters(main, count), done)

    def _prepare_hybrid(self, start, end, main, count):
        if getattr(self, '_hybrid_preparing', False):
            return
        if end - 1 > MAX_TARGET:
            self._offer_hybrid_primesieve(start, end)
            return
        self._hybrid_preparing = True
        snapshot = self._hybrid_input_snapshot()
        self.quick_status_var.set(self.T("quick.hybrid_status_checking"))

        def done(result, error):
            self._hybrid_preparing = False
            if snapshot != self._hybrid_input_snapshot():
                self.quick_status_var.set(self.T("quick.hybrid_status_settings_changed"))
                return
            if error:
                self.quick_status_var.set(self.T("quick.hybrid_status_prepare_failed"))
                messagebox.showerror(self.T("quick.hybrid_error_title"),
                                      error + self.T("quick.hybrid_error_fix_hint"))
                return
            self.quick_hybrid_main_cap_var.set(str(result['main']))
            self.quick_hybrid_filter_prime_count_var.set(str(result['count']))
            if (main, count) != (result['main'], result['count']):
                message = self.T("quick.hybrid_status_adjusted", main=main, new_main=result['main'],
                                  count=count, new_count=result['count'], limit=result['limit'])
                self.quick_status_var.set(message)
                self.loop_console.append(message + '\n')
            else:
                self.quick_status_var.set(self.T("quick.hybrid_status_covers_window"))
            self._on_run_hybrid_narrow(start, end, result['main'], result['count'])

        self._hybrid_async(lambda: parameters(main, count, end), done)

    def _hybrid_input_snapshot(self):
        return tuple(var.get() for var in (
            self.quick_mode_var, self.quick_hybrid_target_var, self.quick_hybrid_value_var,
            self.quick_hybrid_target_floor_var, self.quick_hybrid_main_cap_var,
            self.quick_hybrid_filter_prime_count_var, self._loop_write_files_var))

    def _offer_hybrid_primesieve(self, start, end):
        if not messagebox.askyesno(self.T("quick.hybrid_limit_title"),
                self.T("quick.hybrid_limit_confirm_switch", start=start, end=end, max_target=MAX_TARGET)):
            self.quick_status_var.set(self.T("quick.hybrid_status_not_started"))
            return
        self.quick_primesieve_from_var.set(str(start))
        self.quick_primesieve_floor_var.set(str(len(str(start)) - 1))
        self.quick_primesieve_width_var.set(str((end - start) // 10_000_000))
        self.quick_mode_var.set('primesieve')
        self._on_quick_mode_changed()
        self._on_quick_generate_clicked()
