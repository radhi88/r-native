"""Test suite for Qader REAL_CONTROLLED_MODE unlock persistence fix."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_imports_check() -> None:
    """Verify critical imports work."""
    from qader_app.storage.settings_store import PermissionsStore, RealModeService

    assert PermissionsStore is not None
    assert RealModeService is not None


def test_wrong_phrase_does_not_relock_if_already_unlocked() -> None:
    """Test the core fix: wrong phrase when already unlocked should NOT relock."""
    from qader_app.storage.settings_store import PermissionsStore

    store = PermissionsStore()

    clean_lockdown = {
        "exit_code": 0,
        "open_positions": 0,
        "pending_orders": 0,
        "external_magic0_exposure": False,
        "clean": True,
    }

    with patch("qader_app.storage.settings_store.permissions_path") as mock_path:
        with tempfile.TemporaryDirectory() as tmpdir:
            perm_file = Path(tmpdir) / "permissions.json"
            mock_path.return_value = perm_file

            result1 = store.unlock_real_controlled_mode("I ACCEPT REAL TRADING RISK", clean_lockdown)
            assert result1.get("can_place_live_orders") is True
            assert result1.get("_real_controlled_mode_unlocked") is True

            result2 = store.unlock_real_controlled_mode("WRONG PHRASE", clean_lockdown)
            assert result2.get("can_place_live_orders") is True, "Wrong phrase should NOT relock if already unlocked!"
            assert result2.get("_real_controlled_mode_unlocked") is True, "Unlock state must persist!"
            assert result2.get("_unlock_error") == "confirmation_phrase_mismatch"


def test_wrong_phrase_locks_if_not_already_unlocked() -> None:
    """Test that wrong phrase locks when NOT already unlocked."""
    from qader_app.storage.settings_store import PermissionsStore

    store = PermissionsStore()

    clean_lockdown = {
        "exit_code": 0,
        "open_positions": 0,
        "pending_orders": 0,
        "external_magic0_exposure": False,
        "clean": True,
    }

    with patch("qader_app.storage.settings_store.permissions_path") as mock_path:
        with tempfile.TemporaryDirectory() as tmpdir:
            perm_file = Path(tmpdir) / "permissions.json"
            mock_path.return_value = perm_file

            result = store.unlock_real_controlled_mode("WRONG PHRASE", clean_lockdown)
            assert result.get("can_place_live_orders") is False, "Wrong phrase should lock!"
            assert result.get("_real_controlled_mode_unlocked") is False
            assert result.get("_unlock_error") == "confirmation_phrase_mismatch"


def test_lock_button_functionality() -> None:
    """Test that explicit lock button works."""
    from qader_app.storage.settings_store import PermissionsStore

    store = PermissionsStore()

    with patch("qader_app.storage.settings_store.permissions_path") as mock_path:
        with tempfile.TemporaryDirectory() as tmpdir:
            perm_file = Path(tmpdir) / "permissions.json"
            mock_path.return_value = perm_file

            result = store.lock_real_controlled_mode("manual_lock_via_gui")
            assert result.get("can_place_live_orders") is False
            assert result.get("_real_controlled_mode_unlocked") is False
            assert result.get("_real_lock_reason") == "manual_lock_via_gui"


def test_auto_start_flag_persists() -> None:
    """Test that auto-start flag is saved and loaded."""
    from qader_app.storage.settings_store import PermissionsStore

    store = PermissionsStore()

    with patch("qader_app.storage.settings_store.permissions_path") as mock_path:
        with tempfile.TemporaryDirectory() as tmpdir:
            perm_file = Path(tmpdir) / "permissions.json"
            mock_path.return_value = perm_file

            data = store.load()
            data["_auto_start_real_controlled_mode"] = True
            result = store.save(data)

            assert result.get("_auto_start_real_controlled_mode") is True

            loaded = store.load()
            assert loaded.get("_auto_start_real_controlled_mode") is True


def test_lockdown_verification_timestamp_persists() -> None:
    """Test that lockdown verification timestamp is preserved."""
    from qader_app.storage.settings_store import PermissionsStore

    store = PermissionsStore()

    clean_lockdown = {
        "exit_code": 0,
        "open_positions": 0,
        "pending_orders": 0,
        "external_magic0_exposure": False,
        "clean": True,
    }

    with patch("qader_app.storage.settings_store.permissions_path") as mock_path:
        with tempfile.TemporaryDirectory() as tmpdir:
            perm_file = Path(tmpdir) / "permissions.json"
            mock_path.return_value = perm_file

            result1 = store.unlock_real_controlled_mode("I ACCEPT REAL TRADING RISK", clean_lockdown)
            timestamp1 = result1.get("_real_lockdown_verified_at")
            assert timestamp1 is not None

            result2 = store.unlock_real_controlled_mode("WRONG PHRASE", clean_lockdown)
            timestamp2 = result2.get("_real_lockdown_verified_at")
            assert timestamp2 == timestamp1, "Timestamp should persist when wrong phrase is ignored while already unlocked!"


def test_gui_controls_load() -> None:
    """Test that GUI controls initialize without errors."""
    try:
        from qader_app.gui.real_controlled import RealControlledModeView
        from qader_app.services.real_mode_service import RealModeService

        service = RealModeService()
        view = RealControlledModeView(service)
        assert hasattr(view, "auto_start_toggle")
        assert hasattr(view, "lock_button")
        assert hasattr(view, "arm_start_button")
        assert hasattr(view, "emergency_button")
    except Exception as exc:
        pytest.fail(f"GUI initialization failed: {exc}")


def test_real_mode_service_imports() -> None:
    """Test that RealModeService can be imported and instantiated."""
    from qader_app.services.real_mode_service import RealModeService
    from qader_app.storage.settings_store import PermissionsStore

    service = RealModeService(permissions=PermissionsStore())
    assert service is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
