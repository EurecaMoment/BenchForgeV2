"""Keep the new Isaac RPC namespace compatible with existing peers."""
from collections import namedtuple

import grpc


SERVICE = 'benchforge.isaac.IsaacSim'
LEGACY_SERVICE = 'spatialforge.isaac.IsaacSim'
_RPCDetails = namedtuple('_RPCDetails', ('method', 'invocation_metadata'))


class _ServiceAlias(grpc.GenericRpcHandler):
    def __init__(self, server):
        self.server = server

    def service(self, call):
        if call.method.startswith('/' + LEGACY_SERVICE + '/'):
            return self.server.service(_RPCDetails(
                call.method.replace(LEGACY_SERVICE, SERVICE, 1), call.invocation_metadata
            ))
        return None


def register_isaac_service(servicer, server, register):
    # Capture the generated method handlers once, then serve both names.
    class Registrar:
        def add_generic_rpc_handlers(self, handlers):
            server.add_generic_rpc_handlers((
                *handlers, *(_ServiceAlias(handler) for handler in handlers)
            ))

        def add_registered_method_handlers(self, name, handlers):
            server.add_registered_method_handlers(name, handlers)

    register(servicer, Registrar())


class IsaacChannel:
    """Retry only when the peer has no RPC under the new namespace."""
    def __init__(self, channel):
        self._channel = channel

    def _method(self, method, path, **kwargs):
        current = method(path, **kwargs)
        legacy = method(path.replace(SERVICE, LEGACY_SERVICE, 1), **kwargs)
        return current, legacy

    @staticmethod
    def _unimplemented(error):
        return error.code() == grpc.StatusCode.UNIMPLEMENTED and error.details() in {
            'Method not found!', 'Method not found', ''
        }

    def unary_unary(self, path, **kwargs):
        current, legacy = self._method(self._channel.unary_unary, path, **kwargs)

        def call(request, *args, **options):
            try:
                return current(request, *args, **options)
            except grpc.RpcError as error:
                if not self._unimplemented(error):
                    raise
                return legacy(request, *args, **options)
        return call

    def stream_unary(self, path, **kwargs):
        current, legacy = self._method(self._channel.stream_unary, path, **kwargs)

        def call(requests, *args, **options):
            try:
                return current(requests(), *args, **options)
            except grpc.RpcError as error:
                if not self._unimplemented(error):
                    raise
                return legacy(requests(), *args, **options)
        return call

    def unary_stream(self, path, **kwargs):
        current, legacy = self._method(self._channel.unary_stream, path, **kwargs)

        def call(request, *args, **options):
            started = False
            try:
                for response in current(request, *args, **options):
                    started = True
                    yield response
            except grpc.RpcError as error:
                if started or not self._unimplemented(error):
                    raise
                yield from legacy(request, *args, **options)
        return call
