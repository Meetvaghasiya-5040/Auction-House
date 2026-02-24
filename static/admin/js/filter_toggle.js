// static/admin/js/filter_toggle.js
function toggleFilters() {
  const filters = document.querySelector('[data-unfold-filters]');
  if (!filters) return;

  filters.classList.toggle('hidden');
}