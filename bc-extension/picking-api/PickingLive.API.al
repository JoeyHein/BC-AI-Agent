/// <summary>
/// Read-only APIs over the LIVE (non-archived) picking state.
///
/// Both source tables are transient: ArchiveAndCleanup DELETES Picking Selection
/// rows on post, and flags Picker Session rows as archived. So these endpoints
/// answer "what is happening right now", never "what happened last week".
/// For history use the postedPicking* endpoints.
/// </summary>
page 70136 "Upwardor API Picking Queue"
{
    PageType = API;
    Caption = 'Picking Selection';
    APIPublisher = 'upwardor';
    APIGroup = 'picking';
    APIVersion = 'v1.0';
    EntityName = 'pickingQueueItem';
    EntitySetName = 'pickingQueue';
    SourceTable = "Picking Selection";
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
                field(salesOrderNo; Rec."Sales Order No.")
                {
                    Caption = 'salesOrderNo';
                }
                field(customerNo; Rec."Customer No.")
                {
                    Caption = 'customerNo';
                }
                field(customerName; Rec."Customer Name")
                {
                    Caption = 'customerName';
                }
                field(externalDocumentNo; Rec."External Document No.")
                {
                    Caption = 'externalDocumentNo';
                }
                field(shipmentDate; Rec."Shipment Date")
                {
                    Caption = 'shipmentDate';
                }
                field(pickingDate; Rec."Picking Date")
                {
                    Caption = 'pickingDate';
                }
                field(status; Rec.Status)
                {
                    Caption = 'status';
                }
                field(loadMethod; Rec."Load Method")
                {
                    Caption = 'loadMethod';
                }
                field(pickedByNo; Rec."Picked By No.")
                {
                    Caption = 'pickedByNo';
                }
                field(pickerName; Rec."Picker Name")
                {
                    Caption = 'pickerName';
                }
                field(pickerSessionEntryNo; Rec."Picker Session Entry No.")
                {
                    Caption = 'pickerSessionEntryNo';
                }
                field(selectedBy; Rec."Selected By")
                {
                    Caption = 'selectedBy';
                }
                field(selectedAt; Rec."Selected At")
                {
                    Caption = 'selectedAt';
                }
                field(lastModifiedDateTime; Rec.SystemModifiedAt)
                {
                    Caption = 'lastModifiedDateTime';
                }
            }
        }
    }
}

page 70137 "Upwardor API Picker Session"
{
    PageType = API;
    Caption = 'Picker Session';
    APIPublisher = 'upwardor';
    APIGroup = 'picking';
    APIVersion = 'v1.0';
    EntityName = 'pickerSession';
    EntitySetName = 'pickerSessions';
    SourceTable = "Picker Session";
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
                field(startedAt; Rec."Started At")
                {
                    Caption = 'startedAt';
                }
                field(status; Rec.Status)
                {
                    Caption = 'status';
                }
                field(archived; Rec.Archived)
                {
                    Caption = 'archived';
                }
                field(lastModifiedDateTime; Rec.SystemModifiedAt)
                {
                    Caption = 'lastModifiedDateTime';
                }
            }
        }
    }
}
