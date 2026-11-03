"""
paging.py -- page-based rendering shared by the preview lists of several tabs: fill a
listbox with one page of values, and update the "Page X / Y" label and Prev/Next
buttons. Injected into the tab classes (render_page=, update_nav_controls=).
"""
from primeatlas.app import app_dynamic as _dyn


def render_page(listbox, values, page, page_size, formatter):
    """Replaces `listbox`'s contents with page `page` (0-indexed) of `values`, rendering
    each entry with `formatter(value) -> str`. Page-based navigation (as opposed to the
    earlier cumulative "load more" approach): each call fully replaces what's shown, so
    there's no growing/duplicate-trailer state to track -- Prev/Next/jump-to-page just
    call this again with a different page index. Returns (clamped_page, total_pages)."""
    total = len(values)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    listbox.delete(0, "end")
    start = page * page_size
    end = min(start + page_size, total)
    for v in values[start:end]:
        listbox.insert("end", formatter(v))
    return page, total_pages


def update_nav_controls(page_label_var, page, total_pages, prev_btn, next_btn):
    """Shared by both preview panes: updates the "Page X / Y" label and enables/disables
    the Prev/Next buttons at the boundaries."""
    page_label_var.set(_dyn.T("common.page_label", page=page + 1, total=total_pages))
    prev_btn.configure(state="normal" if page > 0 else "disabled")
    next_btn.configure(state="normal" if page < total_pages - 1 else "disabled")
