"""Identity-preserving fixture results for mocked host acquisition passes."""
from kiss_cli import flowgate


def approved_result(project, result):
    flow = flowgate.load()
    return dict(result, approval_sha256=flow.approval.approval_id(flow.approval.read(project)))
