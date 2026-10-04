"""Guided publication controls, separate from task acceptance and live pilot authority."""

from django import forms
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from engine.privacy import PrivacyError
from engine.schemas import ValidationError

from . import authorization, company_learning
from .control_views import SensitiveForm
from .forms import SelectorMultipleField
from .models import EvidenceReview
from .presentation import review_page
from .views import protected, _form_error


class PublicationForm(SensitiveForm):
    multiple_fields = ("repositories",)
    repositories = SelectorMultipleField(choices=(), widget=forms.CheckboxSelectMultiple, label="Future suggestion repositories", required=False)
    action = forms.ChoiceField(choices=(("publish", "Publish this reviewed learner for manual suggestions"), ("default_only", "Stop learned suggestions; retain static/default baseline")))
    expected_sequence = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    reason = forms.CharField(max_length=256)
    confirmation = forms.BooleanField(label="I reviewed the exact artifact/repository scope; publication is not pilot approval")

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["repositories"].choices = [(item, item) for item in company.repository_refs]


@sensitive_post_parameters("__ALL__")
@protected()
@require_http_methods(["GET", "POST"])
def publish(request, reference):
    member = authorization._reviewer(request)
    review = EvidenceReview.objects.filter(company=member.company, reference=reference).first()
    if review is None:
        raise PermissionDenied("Review is unavailable for this company.")
    source = review.data["learner"]["plan"]["source_kind"]
    rows = company_learning.history(member.company, source)
    form = PublicationForm(request.POST if request.method == "POST" else None, company=member.company,
                           initial={"expected_sequence": rows[-1].sequence if rows else 0})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            company_learning.change(request, data["confirm_password"], data["code"], source, data["expected_sequence"], data["reason"],
                                    review_ref=reference if data["action"] == "publish" else None, repositories=data["repositories"])
        except (ValidationError, PrivacyError, PermissionDenied) as error:
            _form_error(form, error)
        else:
            return redirect("company-learning")
    form.sanitize_display()
    return render(request, "company/learning_publish.html", {**review_page(review, member.company), "form": form})


@protected()
@require_http_methods(["GET"])
def index(request):
    member = authorization._reviewer(request)
    sources = []
    for source in ("synthetic", "team"):
        rows = company_learning.history(member.company, source)
        sources.append({"kind": source, "history": rows, "current": rows[-1] if rows else None,
                        "guard": company_learning.guard(rows[-1] if rows else None, member.company)})
    return render(request, "company/learning.html", {"sources": sources})
