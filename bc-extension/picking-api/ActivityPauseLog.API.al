/// <summary>
/// Read-only API over pause/downtime records.
///
/// Joins back to activityTimeLogs on activityEntryNo. A row with a null/zero
/// pauseEnd is an OPEN pause - durationMinutes is not yet stamped for those,
/// so consumers must compute live age from pauseStart themselves.
///
/// reason separates 'Equipment Issue' from 'Break'/'Lunch', which is the
/// operationally useful distinction for downtime reporting.
/// </summary>
page 70135 "Upwardor API Pause Log"
{
    PageType = API;
    Caption = 'Activity Pause Log';
    APIPublisher = 'upwardor';
    APIGroup = 'picking';
    APIVersion = 'v1.0';
    EntityName = 'activityPauseLog';
    EntitySetName = 'activityPauseLogs';
    SourceTable = "Activity Pause Log";
    ODataKeyFields = SystemId;
    Extensible = false;
    Editable = false;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    DataAccessIntent = ReadOnly;

    layout
    {
        area(Content)
        {
            repeater(Group)
            {
                field(systemId; Rec.SystemId)
                {
                    Caption = 'systemId';
                }
                field(activityEntryNo; Rec."Activity Entry No.")
                {
                    Caption = 'activityEntryNo';
                }
                field(pauseNo; Rec."Pause No.")
                {
                    Caption = 'pauseNo';
                }
                field(pauseStart; Rec."Pause Start")
                {
                    Caption = 'pauseStart';
                }
                field(pauseEnd; Rec."Pause End")
                {
                    Caption = 'pauseEnd';
                }
                field(durationMinutes; Rec."Duration Minutes")
                {
                    Caption = 'durationMinutes';
                }
                field(reason; Rec.Reason)
                {
                    Caption = 'reason';
                }
                field(lastModifiedDateTime; Rec.SystemModifiedAt)
                {
                    Caption = 'lastModifiedDateTime';
                }
            }
        }
    }
}
