/// <summary>
/// Read-only permission set for external/integration consumers of the picking
/// API (the OPENDC portal, BI, scheduling tools).
///
/// Deliberately NOT built on "Picking System" - that grants RIMD on the working
/// tables and execute on the picker UI pages. An integration account needs
/// neither. Everything here is R / X only.
/// </summary>
permissionset 70102 "Picking API Read"
{
    Caption = 'Picking API - Read Only';
    Assignable = true;

    Permissions =
        // Tables - read only
        tabledata "Activity Time Log" = R,
        tabledata "Activity Pause Log" = R,
        tabledata "Picker Session" = R,
        tabledata "Picking Selection" = R,
        tabledata "Picking Entry" = R,
        tabledata "Posted Picking Session" = R,
        tabledata "Posted Picking Header" = R,
        tabledata "Posted Picking Line" = R,

        // API pages
        page "Upwardor API Activity Log" = X,
        page "Upwardor API Pause Log" = X,
        page "Upwardor API Picking Queue" = X,
        page "Upwardor API Picking Entry" = X,
        page "Upwardor API Picker Session" = X,
        page "Upwardor API Posted Session" = X,
        page "Upwardor API Posted Header" = X,
        page "Upwardor API Posted Line" = X,

        // Required by the elapsed-time computation on the activity log API
        codeunit "Activity Time Management" = X;
}
