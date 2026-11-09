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
    'bridge_target_unverified', 'bridge_connection_failed', 'bridge_initialization_failed',
    'bridge_dependency_missing', 'bridge_dependency_unreadable',
    'bridge_dependency_incompatible', 'bridge_dependency_load_failed',
})
MANAGED_TYPES = frozenset({'other', 'System.InvalidOperationException', 'System.TypeInitializationException',
    'System.TypeLoadException', 'System.MissingMethodException', 'System.MissingFieldException',
    'System.NullReferenceException', 'System.ArgumentException', 'System.ArgumentNullException',
    'System.NotSupportedException', 'System.BadImageFormatException', 'System.IO.FileNotFoundException',
    'System.IO.DirectoryNotFoundException', 'System.IO.FileLoadException', 'System.IO.IOException',
    'System.UnauthorizedAccessException', 'System.Security.SecurityException',
    'System.Reflection.TargetInvocationException', 'Newtonsoft.Json.JsonReaderException',
    'System.InvalidCastException', 'System.OverflowException', 'System.OutOfMemoryException'})
INITIALIZATION_STEPS = {f'bridge_init_{i}': name for i, name in enumerate((
    'read_session', 'validate_session', 'verify_assemblies', 'read_ledger',
    'bind_game_fields', 'bind_main_loop', 'register_main_loop'), 1)}
INITIALIZATION_STEPS['bridge_init_0'] = 'invoke_install'
MANAGED_REASONS = {name: name for name in ('process_unverified', 'process_mismatch', 'invalid_session',
    'automation_files_changed', 'ledger_mismatch', 'ledger_invalid', 'missing_duplicates', 'oversized_request')}
MANAGED_REASONS.update({'missing_field:' + name: 'missing_' + name.lstrip('_') for name in (
    '_exchangeSlots', '_isExchanging', '_possibleExchanges', '_currentCategoryTabIndex', '_exchanges',
    '_mResultHandles', 's_OrderBlocks', 'order', 'callback')})
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
    for key, allowed in (('initialization_step', INITIALIZATION_STEPS.values()),
                         ('managed_reason', MANAGED_REASONS.values())):
        if isinstance(value.get(key), str) and value[key] in allowed:
            result[key] = value[key]
    chain = value.get('managed_exception_types')
    if isinstance(chain, list) and 0 < len(chain) <= 3 and all(isinstance(v, str) and v in MANAGED_TYPES for v in chain):
        result['managed_exception_types'] = list(chain)
    return result


def connection_error(value):
    return value if isinstance(value, str) and value in CONNECTION_ERRORS else 'bridge_connection_failed'


def initialization_error(details):
    """A type-load failure does not prove that any particular DLL is missing."""
    types = clean_details(details).get('managed_exception_types', [])
    if any(kind in {'System.TypeLoadException', 'System.MissingMethodException',
                   'System.MissingFieldException', 'System.IO.FileLoadException',
                   'System.BadImageFormatException'} for kind in types):
        return 'bridge_dependency_load_failed'
    return 'bridge_initialization_failed'
