"""Small allowlisted diagnostics. Never serialize exceptions or session files."""

CONNECTION_ERRORS = frozenset({
    'game_missing_or_ambiguous', 'unsupported_game_build', 'bridge_assets_missing',
    'bridge_client_in_use', 'prior_bridge_active', 'attach_not_confirmed_no_retry',
    'process_access_failed', 'bridge_session_unavailable', 'bridge_binary_changed',
    'merge_compiler_missing', 'merge_prepare_failed', 'unsupported_game_files',
    'merge_game_files_missing', 'merge_game_files_unreadable', 'automation_probe_failed',
    'automation_files_changed', 'unsupported_automation_features', 'bridge_response_pending',
    'bridge_path_unsupported', 'bridge_storage_access_denied', 'bridge_storage_full',
    'bridge_storage_conflict', 'bridge_storage_failed', 'bridge_storage_security_failed',
    'bridge_module_scan_failed', 'bridge_session_incompatible', 'bridge_session_closed',
    'bridge_session_invalid', 'bridge_response_unreadable', 'bridge_response_invalid',
    'bridge_reconnect_failed', 'bridge_stop_unconfirmed', 'bridge_target_changed',
    'bridge_target_unverified', 'bridge_connection_failed',
})
PHASES = frozenset({'find_game', 'validate_assets', 'open_process', 'session_path',
    'read_session', 'open_channel', 'read_attach_result', 'wait_response', 'stop_previous',
    'refresh_response', 'inspect_modules', 'validate_game', 'prepare_module', 'write_session',
    'bootstrap', 'write_attach_result'})
NATIVE_ERRORS = frozenset({'bootstrap_outcome_unknown_no_retry', 'bootstrap_thread_failed_no_retry',
                         'bootstrap_result_unreadable_no_retry', 'native_os_error', 'native_failed'})


def clean_details(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, allowed in (('phase', PHASES), ('native_error', NATIVE_ERRORS),
                         ('source', {'new', 'existing'}),
                         ('attach_record', {'present', 'missing', 'invalid', 'unreadable'})):
        item = value.get(key)
        if isinstance(item, str) and item in allowed:
            result[key] = item
    for key, maximum in (('status', 2), ('stage', 8), ('load_error', 65535), ('winerror', 65535)):
        item = value.get(key)
        if type(item) is int and 0 <= item <= maximum:
            result[key] = item
    if type(value.get('managed_exception')) is bool:
        result['managed_exception'] = value['managed_exception']
    return result


def connection_error(value):
    return value if isinstance(value, str) and value in CONNECTION_ERRORS else 'bridge_connection_failed'
