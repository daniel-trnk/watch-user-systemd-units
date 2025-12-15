"""Test unit filtering functionality."""

from unittest import mock

import pytest

from systemd_unit_monitor import SystemdUnitMonitor


class TestUnitFiltering:
    """Test unit filtering logic."""

    @pytest.fixture
    def monitor(self):
        """Create a monitor instance with mocked D-Bus."""
        with mock.patch("dbus.mainloop.glib.DBusGMainLoop"), mock.patch("dbus.SessionBus"):
            return SystemdUnitMonitor()

    def test_no_filters_accepts_all(self, monitor):
        """Test that no filters means all units are accepted."""
        monitor.include_patterns = []
        monitor.exclude_patterns = []
        
        assert monitor._should_monitor_unit("nginx.service") is True
        assert monitor._should_monitor_unit("user.mount") is True
        assert monitor._should_monitor_unit("custom.timer") is True

    def test_include_patterns(self, monitor):
        """Test include pattern filtering."""
        monitor.include_patterns = ["*.service", "*.timer"]
        monitor.exclude_patterns = []
        
        assert monitor._should_monitor_unit("nginx.service") is True
        assert monitor._should_monitor_unit("backup.timer") is True
        assert monitor._should_monitor_unit("user.mount") is False
        assert monitor._should_monitor_unit("proc.target") is False

    def test_exclude_patterns(self, monitor):
        """Test exclude pattern filtering."""
        monitor.include_patterns = []
        monitor.exclude_patterns = ["*.mount", "*.swap", "tmp-*"]
        
        assert monitor._should_monitor_unit("nginx.service") is True
        assert monitor._should_monitor_unit("user.mount") is False
        assert monitor._should_monitor_unit("swap.swap") is False
        assert monitor._should_monitor_unit("tmp-1234.service") is False
        assert monitor._should_monitor_unit("backup.timer") is True

    def test_include_and_exclude_patterns(self, monitor):
        """Test combination of include and exclude patterns."""
        monitor.include_patterns = ["*.service"]
        monitor.exclude_patterns = ["tmp-*", "*-debug*"]
        
        # Matches include, not excluded
        assert monitor._should_monitor_unit("nginx.service") is True
        
        # Matches include but excluded
        assert monitor._should_monitor_unit("tmp-worker.service") is False
        assert monitor._should_monitor_unit("app-debug.service") is False
        
        # Doesn't match include
        assert monitor._should_monitor_unit("user.mount") is False

    def test_complex_patterns(self, monitor):
        """Test more complex glob patterns."""
        monitor.include_patterns = ["nginx-*", "*backup*", "app?.service"]
        monitor.exclude_patterns = ["*-test*"]
        
        # Include matches
        assert monitor._should_monitor_unit("nginx-worker.service") is True
        assert monitor._should_monitor_unit("daily-backup.timer") is True
        assert monitor._should_monitor_unit("app1.service") is True
        assert monitor._should_monitor_unit("app2.service") is True
        
        # Include matches but excluded
        assert monitor._should_monitor_unit("nginx-test.service") is False
        assert monitor._should_monitor_unit("backup-test.timer") is False
        
        # No include match
        assert monitor._should_monitor_unit("redis.service") is False
        assert monitor._should_monitor_unit("user.mount") is False

    def test_case_sensitivity(self, monitor):
        """Test that pattern matching is case sensitive."""
        monitor.include_patterns = ["*.Service"]  # Capital S
        monitor.exclude_patterns = []
        
        assert monitor._should_monitor_unit("nginx.service") is False  # lowercase s
        assert monitor._should_monitor_unit("nginx.Service") is True   # uppercase S

    def test_exact_name_matching(self, monitor):
        """Test exact name matching without wildcards."""
        monitor.include_patterns = ["nginx.service", "redis.service"]
        monitor.exclude_patterns = ["nginx.service"]  # Exclude trumps include
        
        assert monitor._should_monitor_unit("nginx.service") is False
        assert monitor._should_monitor_unit("redis.service") is True
        assert monitor._should_monitor_unit("apache.service") is False

    def test_empty_unit_name(self, monitor):
        """Test behavior with empty unit name."""
        monitor.include_patterns = ["*.service"]
        monitor.exclude_patterns = []
        
        assert monitor._should_monitor_unit("") is False

    def test_filter_pattern_precedence(self, monitor):
        """Test that exclude patterns take precedence over include patterns."""
        monitor.include_patterns = ["*"]  # Include everything
        monitor.exclude_patterns = ["*.mount"]
        
        assert monitor._should_monitor_unit("nginx.service") is True
        assert monitor._should_monitor_unit("user.mount") is False  # Excluded wins

    @pytest.mark.parametrize("pattern,unit_name,expected", [
        ("*.service", "nginx.service", True),
        ("*.service", "nginx.timer", False),
        ("nginx-*", "nginx-worker", True),
        ("nginx-*", "apache-worker", False),
        ("app?.service", "app1.service", True),
        ("app?.service", "app10.service", False),  # ? matches single char
        ("*backup*", "daily-backup-job", True),
        ("*backup*", "daily-restore-job", False),
        ("", "any.service", False),  # Empty pattern
        ("any.service", "", False),  # Empty unit name
    ])
    def test_pattern_matching_cases(self, monitor, pattern, unit_name, expected):
        """Test various pattern matching scenarios."""
        monitor.include_patterns = [pattern] if pattern else []
        monitor.exclude_patterns = []
        
        result = monitor._should_monitor_unit(unit_name)
        if pattern:  # Only test if we have a pattern
            assert result is expected
        else:  # Empty pattern should result in no monitoring (no include patterns)
            assert result is True  # No filters = monitor everything