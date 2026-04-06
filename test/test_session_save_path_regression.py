from pathlib import Path
from types import SimpleNamespace

from hnh import view as view_module
from hnh.session_artifacts import create_session_bundle as real_create_session_bundle
from hnh.view import View


class _Emitter:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _ProfileStoreStub:
    def __init__(self):
        self.started_calls = []

    def record_session_started(self, profile_name, bundle):
        self.started_calls.append((profile_name, bundle))


def test_start_session_writes_to_session_save_path_not_app_data(monkeypatch, tmp_path):
    app_data_root = tmp_path / "app-data-root"
    session_save_root = tmp_path / "session-save-root"
    app_data_root.mkdir(parents=True, exist_ok=True)
    session_save_root.mkdir(parents=True, exist_ok=True)

    call_args = {}

    def _capture_create_session_bundle(*, root, profile_id, include_profile_subpath=True):
        call_args["root"] = root
        call_args["profile_id"] = profile_id
        call_args["include_profile_subpath"] = include_profile_subpath
        return real_create_session_bundle(
            root=root,
            profile_id=profile_id,
            include_profile_subpath=include_profile_subpath,
        )

    monkeypatch.setattr(view_module, "create_session_bundle", _capture_create_session_bundle)

    start_recording = _Emitter()
    annotation = _Emitter()
    profile_store = _ProfileStoreStub()
    statuses = []
    state_changes = []
    persisted = []

    view_stub = SimpleNamespace(
        _session_state="idle",
        _session_profile_id="Sandy",
        _session_root=app_data_root,
        _session_bundle=None,
        _session_annotations=["stale"],
        _session_hr_values=[1.0],
        _session_hr_times=[1.0],
        _session_rmssd_values=[1.0],
        _session_rmssd_times=[1.0],
        _session_hrv_values=[1.0],
        _session_hrv_times=[1.0],
        _session_reset_markers_seconds=[1.0],
        _session_report_time_offset_seconds=1.0,
        _session_stress_ratio_values=[1.0],
        _session_stress_ratio_times=[1.0],
        _session_snr_values=[1.0],
        _session_qtc_payload={},
        _last_qtc_diag_logged=("x",),
        _disconnect_intervals=[{"start": 1.0}],
        _profile_store=profile_store,
        signals=SimpleNamespace(start_recording=start_recording, annotation=annotation),
        _is_sensor_connected=lambda: True,
        _session_save_path_from_settings=lambda: session_save_root,
        _current_disclaimer_payload=lambda: {
            "warning": "w",
            "sha256": "h",
            "acknowledgment_mode": "not_recorded",
            "acknowledged_at": None,
        },
        _set_session_state=lambda new_state: state_changes.append(new_state),
        _persist_manifest=lambda **kwargs: persisted.append(kwargs),
        show_status=lambda msg: statuses.append(msg),
    )

    View.start_session(view_stub)

    assert call_args["root"] == session_save_root
    assert call_args["profile_id"] == "Sandy"
    assert call_args["include_profile_subpath"] is False

    assert view_stub._session_bundle is not None
    assert view_stub._session_bundle.session_dir.exists()
    assert session_save_root in view_stub._session_bundle.session_dir.parents
    assert app_data_root not in view_stub._session_bundle.session_dir.parents
    assert not any(app_data_root.rglob("*"))
