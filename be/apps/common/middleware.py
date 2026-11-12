import uuid


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        response = self.get_response(request)
        response["X-Request-Id"] = request.request_id
        return response
