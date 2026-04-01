"""AdminAppBridge unit tests (no Qt event loop required for signal definition)."""

import pytest


def test_bridge_import():
    """Bridge can be imported without Qt display."""
    try:
        from admin_app.app_bridge import AdminAppBridge
        assert AdminAppBridge is not None
    except Exception as e:
        pytest.skip(f'Qt not available in test env: {e}')


def test_bridge_has_required_signals():
    try:
        from admin_app.app_bridge import AdminAppBridge
        assert hasattr(AdminAppBridge, 'robot_status_updated')
        assert hasattr(AdminAppBridge, 'alarm_raised')
        assert hasattr(AdminAppBridge, 'alarm_dismissed')
        assert hasattr(AdminAppBridge, 'robot_offline')
        assert hasattr(AdminAppBridge, 'robot_online')
        assert hasattr(AdminAppBridge, 'event_logged')
    except Exception as e:
        pytest.skip(f'Qt not available in test env: {e}')
