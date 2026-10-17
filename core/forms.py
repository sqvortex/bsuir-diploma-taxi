from django import forms
from django.utils import timezone


class BootstrapFormMixin:
    """Добавляет полям формы CSS-класс Bootstrap, чтобы не прописывать его вручную в шаблонах."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            field.widget.attrs["class"] = f"{field.widget.attrs.get('class', '')} {css}".strip()


class SearchForm(BootstrapFormMixin, forms.Form):
    """Форма поиска рейсов на главной странице (ФТ-2)."""

    from_city = forms.CharField(label="Откуда", max_length=100)
    to_city = forms.CharField(label="Куда", max_length=100)
    date = forms.DateField(
        label="Когда", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )

    def clean(self):
        data = super().clean()
        if data.get("from_city") and data.get("to_city"):
            if data["from_city"].strip().lower() == data["to_city"].strip().lower():
                raise forms.ValidationError("Города отправления и прибытия должны различаться.")
        if data.get("date") and data["date"] < timezone.localdate():
            self.add_error("date", "Нельзя искать рейсы в прошлом.")
        return data
