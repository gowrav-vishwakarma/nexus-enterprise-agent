# Regenerate gRPC stubs after editing media.proto:
#   uv run python -m grpc_tools.protoc \
#     -I nexus/server/proto \
#     --python_out=nexus/server/proto \
#     --grpc_python_out=nexus/server/proto \
#     nexus/server/proto/media.proto
# Then fix import in media_pb2_grpc.py:
#   from nexus.server.proto import media_pb2 as media__pb2
