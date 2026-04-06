class HtmxMiddleware:
    """Simple HTMX middleware for Django 3.0 compatibility."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check if this is an HTMX request
        request.htmx = bool(request.META.get('HTTP_HX_REQUEST') == 'true')
        response = self.get_response(request)
        return response
