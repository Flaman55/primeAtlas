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
            self.quick_hybrid_range_var.set('Wprowadź całkowite wartości MAIN i filtra.')
            return
        self.quick_hybrid_range_var.set('Obliczanie zasięgu…')

        def done(result, error):
            if version != self._hybrid_preview_version:
                return
            if error:
                self.quick_hybrid_range_var.set(error)
                return
            text = (f"Zasięg: do {result['limit']:,} | MAIN ≤ {result['main_max']:,} "
                    f"dla tego filtra | limit Hybrydy: {MAX_TARGET:,}")
            try:
                _, end = self._hybrid_selected_range()
                text += ' | Przy starcie: minimalny MAIN, potem najmniejszy wystarczający filtr'
                if end - 1 > MAX_TARGET:
                    text = text.rsplit(' | ', 1)[0] + ' | Cel wymaga primesieve'
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
        self.quick_status_var.set('Sprawdzanie i dopasowywanie parametrów Hybrydy…')

        def done(result, error):
            self._hybrid_preparing = False
            if snapshot != self._hybrid_input_snapshot():
                self.quick_status_var.set('Ustawienia zmieniono. Naciśnij Generuj ponownie.')
                return
            if error:
                self.quick_status_var.set('Nie udało się przygotować Hybrydy.')
                messagebox.showerror('Hybryda', error + '\nPopraw parametry lub wybierz primesieve.')
                return
            self.quick_hybrid_main_cap_var.set(str(result['main']))
            self.quick_hybrid_filter_prime_count_var.set(str(result['count']))
            if (main, count) != (result['main'], result['count']):
                message = (f"Dopasowano MAIN: {main:,} → {result['main']:,}; "
                           f"filtr: {count:,} → {result['count']:,}. "
                           f"Zasięg do {result['limit']:,} obejmuje wybrane okno.")
                self.quick_status_var.set(message)
                self.loop_console.append(message + '\n')
            else:
                self.quick_status_var.set('Parametry Hybrydy obejmują wybrane okno.')
            self._on_run_hybrid_narrow(start, end, result['main'], result['count'])

        self._hybrid_async(lambda: parameters(main, count, end), done)

    def _hybrid_input_snapshot(self):
        return tuple(var.get() for var in (
            self.quick_mode_var, self.quick_hybrid_target_var, self.quick_hybrid_value_var,
            self.quick_hybrid_target_floor_var, self.quick_hybrid_main_cap_var,
            self.quick_hybrid_filter_prime_count_var, self._loop_write_files_var))

    def _offer_hybrid_primesieve(self, start, end):
        if not messagebox.askyesno('Limit Hybrydy',
                f'Okno [{start:,}, {end:,}) przekracza limit Hybrydy {MAX_TARGET:,}.\n'
                'Czy przełączyć na primesieve i rozpocząć obliczenia dla tego zakresu?'):
            self.quick_status_var.set('Nie uruchomiono obliczeń. Pozostajesz w trybie Hybrydy.')
            return
        self.quick_primesieve_from_var.set(str(start))
        self.quick_primesieve_floor_var.set(str(len(str(start)) - 1))
        self.quick_primesieve_width_var.set(str((end - start) // 10_000_000))
        self.quick_mode_var.set('primesieve')
        self._on_quick_mode_changed()
        self._on_quick_generate_clicked()
