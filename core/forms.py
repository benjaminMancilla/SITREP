from django import forms

INPUT_CLASSES = (
    "mt-1 w-full rounded-lg border border-surface-border bg-white px-3 py-2 "
    "text-[14px] text-ink placeholder:text-ink-secondary focus:border-brand "
    "focus:outline-none focus:ring-2 focus:ring-brand/20"
)


class ContactoForm(forms.Form):
    nombre = forms.CharField(
        max_length=120,
        widget=forms.TextInput(attrs={"class": INPUT_CLASSES, "placeholder": "Tu nombre"}),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": INPUT_CLASSES, "placeholder": "tu@empresa.cl"}),
    )
    naviera = forms.CharField(
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CLASSES, "placeholder": "Naviera o empresa (opcional)"}),
    )
    mensaje = forms.CharField(
        widget=forms.Textarea(attrs={"class": INPUT_CLASSES, "rows": 4, "placeholder": "Cuéntanos qué necesitas"}),
    )
    # Honeypot: oculto por CSS, invisible para humanos. Si viene lleno es un bot.
    pagina_web = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off", "tabindex": "-1"}),
    )

    def is_spam(self):
        return bool(self.cleaned_data.get("pagina_web"))
