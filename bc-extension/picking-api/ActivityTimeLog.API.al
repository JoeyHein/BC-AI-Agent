/// <summary>
/// Read-only API over the picking/loading time-and-motion log.
///
/// Granularity note: Source No. / Source Line No. are currently written as ''/0
/// by both live callers, so rows attribute to (employee x customer x activity type
/// x date), NOT to a sales order or line. They are exposed here anyway so consumers
/// pick them up automatically if the call sites are fixed later.
///
/// elapsedMinutes is computed live for Active/Paused rows only (netDurationMinutes
/// is not stamped until CompleteActivity). Completed rows return the stored value
/// to avoid a pause-log scan per row on large result sets.
/// </summary>
page 70134 "Upwardor API Activity Log"
{
    PageType = API;
    Caption = 'Activity Time Log';
    APIPublisher = 'upwardor';
    APIGroup = 'picking';
    APIVersion = 'v1.0';
    EntityName = 'activityTimeLog';
    EntitySetName = 'activityTimeLogs';
    SourceTable = "Activity Time Log";
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
                field(entryNo; Rec."Entry No.")
                {
                    Caption = 'entryNo';
                }
                field(activityType; Rec."Activity Type")
                {
                    Caption = 'activityType';
                }
                field(sourceType; Rec."Source Type")
                {
                    Caption = 'sourceType';
                }
                field(sourceNo; Rec."Source No.")
                {
                    Caption = 'sourceNo';
                }
                field(sourceLineNo; Rec."Source Line No.")
                {
                    Caption = 'sourceLineNo';
                }
                field(customerNo; Rec."Customer No.")
                {
                    Caption = 'customerNo';
                }
                field(employeeNo; Rec."Employee No.")
                {
                    Caption = 'employeeNo';
                }
                field(employeeName; Rec."Employee Name")
                {
                    Caption = 'employeeName';
                }
                field(startDateTime; Rec."Start DateTime")
                {
                    Caption = 'startDateTime';
                }
                field(endDateTime; Rec."End DateTime")
                {
                    Caption = 'endDateTime';
                }
                field(totalPauseMinutes; Rec."Total Pause Minutes")
                {
                    Caption = 'totalPauseMinutes';
                }
                field(netDurationMinutes; Rec."Net Duration Minutes")
                {
                    Caption = 'netDurationMinutes';
                }
                field(elapsedMinutes; ElapsedMinutes)
                {
                    Caption = 'elapsedMinutes';
                }
                field(status; Rec.Status)
                {
                    Caption = 'status';
                }
                field(activityDate; Rec."Activity Date")
                {
                    Caption = 'activityDate';
                }
                field(pickerSessionEntryNo; Rec."Picker Session Entry No.")
                {
                    Caption = 'pickerSessionEntryNo';
                }
                field(postedSessionEntryNo; Rec."Posted Session Entry No.")
                {
                    Caption = 'postedSessionEntryNo';
                }
                field(archived; Rec.Archived)
                {
                    Caption = 'archived';
                }
                field(createdBy; Rec."Created By")
                {
                    Caption = 'createdBy';
                }
                field(lastModifiedDateTime; Rec.SystemModifiedAt)
                {
                    Caption = 'lastModifiedDateTime';
                }
            }
        }
    }

    var
        ElapsedMinutes: Decimal;

    trigger OnAfterGetRecord()
    var
        ActivityTimeMgmt: Codeunit "Activity Time Management";
    begin
        // Only recompute for running activities. Completed rows already carry a
        // stamped value, and CalcNetDuration scans the pause log per row.
        if Rec.Status = Rec.Status::Completed then
            ElapsedMinutes := Rec."Net Duration Minutes"
        else
            ElapsedMinutes := ActivityTimeMgmt.CalcNetDuration(Rec);
    end;
}
