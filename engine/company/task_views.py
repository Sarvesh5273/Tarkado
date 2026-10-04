from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from engine.privacy import PrivacyError
from engine.schemas import ValidationError

from .task_forms import ExecutionForm, ResponseForm, ResultForm, TaskForm
from .tasks import company_feedback, get_task, recommend_task, record_execution, record_response, record_result, task_detail
from .views import _form_error, _form_page, protected
from .presentation import task_card, task_page


@protected()
@require_http_methods(["GET"])
def tasks(request):
    context = company_feedback(request.user, request=request)
    rows = {row["recommendation_id"]: row for row in context["summary"]["tasks"]}
    from .tasks import task_ledger
    context["cards"] = [task_card(task, rows[task_ledger(task).recommendations[0].recommendation_id]) for task in context["tasks"]]
    return render(request, "company/tasks.html", context)


@sensitive_post_parameters("__ALL__")
@protected()
@require_http_methods(["GET", "POST"])
def new_task(request):
    from .tasks import _participant
    _participant(request.user)
    form = TaskForm(request.POST if request.method == "POST" else None, company=request.company_member.company,
                    initial={"source_kind": "synthetic", "boundary": "new_task"})
    if request.method == "POST" and form.is_valid():
        try:
            task = recommend_task(request.user, form.payload(), request=request)
        except (ValidationError, PrivacyError) as error:
            _form_error(form, error)
        else:
            return redirect("company-task-detail", reference=task.reference)
    return _form_page(request, "company/task_form.html", {"title": "Request a manual shadow suggestion", "form": form})


@protected()
@require_http_methods(["GET"])
def detail(request, reference):
    context = task_page(request, task_detail(request.user, reference, request=request))
    from .models import ConnectorTask
    from .connectors import task_state
    link = ConnectorTask.objects.filter(task=context["task"]).first()
    if link:
        context["connector_state"] = task_state(link)
        context["connector_observations"] = list(link.observations.all())
    return render(request, "company/task_detail.html", context)


@sensitive_post_parameters("__ALL__")
@protected()
@require_http_methods(["GET", "POST"])
def action(request, reference, kind):
    task = get_task(request.user, reference, write=True, own=kind in ("response", "execution"))
    initial = {"expected_revision": task.revision}
    detail = task_page(request, task_detail(request.user, reference, request=request))
    if kind == "result":
        current = detail["current_result"]
        initial.update(desired_result="unknown", tests_passed="unknown", supersedes=current.result_id if current else "")
        if current:
            initial.update(current.to_dict())
            for field in ("desired_result", "tests_passed"):
                initial[field] = {None: "unknown", True: "true", False: "false"}[getattr(current, field)]
            initial["supersedes"] = current.result_id
    form_class = {"response": ResponseForm, "execution": ExecutionForm, "result": ResultForm}[kind]
    options = {"company": request.company_member.company} if kind != "response" else {}
    form = form_class(request.POST if request.method == "POST" else None, initial=initial, **options)
    if request.method == "POST" and form.is_valid():
        try:
            expected = form.cleaned_data["expected_revision"]
            if kind == "response":
                record_response(request.user, reference, form.cleaned_data["response"], expected, request=request)
            elif kind == "execution":
                record_execution(request.user, reference, form.cleaned_data["actual_model"], expected, request=request)
            else:
                record_result(request.user, reference, form.payload(), expected, request=request)
        except (ValidationError, PrivacyError) as error:
            _form_error(form, error)
        else:
            return redirect("company-task-detail", reference=reference)
    title = {"response": "Accept or reject this task only", "execution": "Report the model actually used",
             "result": "Append a correction" if detail["current_result"] else "Record the eventual result"}[kind]
    return _form_page(request, "company/task_form.html", {**detail, "title": title, "form": form, "kind": kind})
