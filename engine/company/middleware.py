class DeploymentBoundaryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        from django.http import HttpResponseBadRequest
        if settings.TARKADO_SERVICE_MODE == "company_https_proxy":
            # Never trust arbitrary forwarded headers in Django. Waitress resolves
            # the scheme only from the explicitly allowed private socket proxy.
            origin = ("https://" if request.is_secure() else "http://") + request.get_host()
            if not request.is_secure() or origin != settings.TARKADO_PUBLIC_ORIGIN:
                return HttpResponseBadRequest("This deployment requires its exact protected HTTPS origin.")
        return self.get_response(request)


class PrivateResponsesMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Cache-Control"] = "no-store"
        response["Referrer-Policy"] = "no-referrer"
        response["X-Frame-Options"] = "DENY"
        response["Content-Security-Policy"] = "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response
