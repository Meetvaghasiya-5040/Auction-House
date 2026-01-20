document.addEventListener("DOMContentLoaded", function () {
    const categorySelect = document.getElementById("id_category");

    if (!categorySelect) return;

    categorySelect.addEventListener("change", function () {
        const categoryId = this.value;
        if (!categoryId) return;

        fetch(`/admin/get-items-by-category/?category_id=${categoryId}`)
            .then(res => res.json())
            .then(data => {
                const selectBox = document.getElementById("id_items_from");
                selectBox.innerHTML = "";

                data.forEach(item => {
                    const opt = document.createElement("option");
                    opt.value = item.id;
                    opt.textContent = item.text;
                    selectBox.appendChild(opt);
                });
            });
    });
});
