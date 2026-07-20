/// <summary>
/// Read-only APIs over the posted picking archive - the durable history that
/// survives ArchiveAndCleanup. This is the reporting/KPI surface.
///
/// IMPORTANT for consumers of postedPickingSession:
///   pickingDurationMinutes is the SUM of Net Duration Minutes across all
///   pickers on the batch, i.e. LABOUR-minutes (2 pickers x 30 min = 60).
///   Wall-clock is (pickingEnd - pickingStart). They are different numbers and
///   mixing them up will silently corrupt any productivity metric.
///
/// Posted Picking Header fields 11-14 (Picking Start/End/Duration/Pause) are
/// ObsoleteState = Pending and are deliberately NOT exposed here - that timing
/// moved to Posted Picking Session.
/// </summary>
page 70138 "Upwardor API Posted Session"
{
    PageType = API;
    Caption = 'Posted Picking Session';
    APIPublisher = 'upwardor';
    APIGroup = 'picking';
    APIVersion = 'v1.0';
    EntityName = 'postedPickingSession';
    EntitySetName = 'postedPickingSessions';
    SourceTable = "Posted Picking Session";
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
                field(customerName; Rec."Customer Name")
                {
                    Caption = 'customerName';
                }
                field(postingDate; Rec."Posting Date")
                {
                    Caption = 'postingDate';
                }
                field(pickers; Rec.Pickers)
                {
                    Caption = 'pickers';
                }
                field(orderCount; Rec."Order Count")
                {
                    Caption = 'orderCount';
                }
                field(pickingStart; Rec."Picking Start")
                {
                    Caption = 'pickingStart';
                }
                field(pickingEnd; Rec."Picking End")
                {
                    Caption = 'pickingEnd';
                }
                field(pickingDurationMinutes; Rec."Picking Duration (Min.)")
                {
                    Caption = 'pickingDurationMinutes';
                }
                field(pickingPauseMinutes; Rec."Picking Pause (Min.)")
                {
                    Caption = 'pickingPauseMinutes';
                }
                field(loadingStart; Rec."Loading Start")
                {
                    Caption = 'loadingStart';
                }
                field(loadingEnd; Rec."Loading End")
                {
                    Caption = 'loadingEnd';
                }
                field(loadingDurationMinutes; Rec."Loading Duration (Min.)")
                {
                    Caption = 'loadingDurationMinutes';
                }
                field(loadingPauseMinutes; Rec."Loading Pause (Min.)")
                {
                    Caption = 'loadingPauseMinutes';
                }
                field(loadMethod; Rec."Load Method")
                {
                    Caption = 'loadMethod';
                }
                field(shipmentNo; Rec."Shipment No.")
                {
                    Caption = 'shipmentNo';
                }
                field(lastModifiedDateTime; Rec.SystemModifiedAt)
                {
                    Caption = 'lastModifiedDateTime';
                }
            }
        }
    }
}

page 70139 "Upwardor API Posted Header"
{
    PageType = API;
    Caption = 'Posted Picking Header';
    APIPublisher = 'upwardor';
    APIGroup = 'picking';
    APIVersion = 'v1.0';
    EntityName = 'postedPickingHeader';
    EntitySetName = 'postedPickingHeaders';
    SourceTable = "Posted Picking Header";
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
                field(sessionEntryNo; Rec."Session Entry No.")
                {
                    Caption = 'sessionEntryNo';
                }
                field(salesOrderNo; Rec."Sales Order No.")
                {
                    Caption = 'salesOrderNo';
                }
                field(shipmentNo; Rec."Shipment No.")
                {
                    Caption = 'shipmentNo';
                }
                field(customerNo; Rec."Customer No.")
                {
                    Caption = 'customerNo';
                }
                field(customerName; Rec."Customer Name")
                {
                    Caption = 'customerName';
                }
                field(postingDate; Rec."Posting Date")
                {
                    Caption = 'postingDate';
                }
                field(postedBy; Rec."Posted By")
                {
                    Caption = 'postedBy';
                }
                field(pickers; Rec.Pickers)
                {
                    Caption = 'pickers';
                }
                field(hasDiscrepancy; Rec."Has Discrepancy")
                {
                    Caption = 'hasDiscrepancy';
                }
                field(sheetNo; Rec."Sheet No.")
                {
                    Caption = 'sheetNo';
                }
                field(lastModifiedDateTime; Rec.SystemModifiedAt)
                {
                    Caption = 'lastModifiedDateTime';
                }
            }
        }
    }
}

page 70140 "Upwardor API Posted Line"
{
    PageType = API;
    Caption = 'Posted Picking Line';
    APIPublisher = 'upwardor';
    APIGroup = 'picking';
    APIVersion = 'v1.0';
    EntityName = 'postedPickingLine';
    EntitySetName = 'postedPickingLines';
    SourceTable = "Posted Picking Line";
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
                field(lineNo; Rec."Line No.")
                {
                    Caption = 'lineNo';
                }
                field(sessionEntryNo; Rec."Session Entry No.")
                {
                    Caption = 'sessionEntryNo';
                }
                field(salesOrderNo; Rec."Sales Order No.")
                {
                    Caption = 'salesOrderNo';
                }
                field(salesLineNo; Rec."Sales Line No.")
                {
                    Caption = 'salesLineNo';
                }
                field(itemNo; Rec."Item No.")
                {
                    Caption = 'itemNo';
                }
                field(description; Rec.Description)
                {
                    Caption = 'description';
                }
                field(unitOfMeasureCode; Rec."Unit of Measure Code")
                {
                    Caption = 'unitOfMeasureCode';
                }
                field(outstandingQty; Rec."Outstanding Qty.")
                {
                    Caption = 'outstandingQty';
                }
                field(qtyPicked; Rec."Qty. Picked")
                {
                    Caption = 'qtyPicked';
                }
                field(qtyLoaded; Rec."Qty. Loaded")
                {
                    Caption = 'qtyLoaded';
                }
                field(loadStatus; Rec."Load Status")
                {
                    Caption = 'loadStatus';
                }
                field(pickerName; Rec."Picker Name")
                {
                    Caption = 'pickerName';
                }
                field(loaderName; Rec."Loader Name")
                {
                    Caption = 'loaderName';
                }
                field(isCommentLine; Rec."Is Comment Line")
                {
                    Caption = 'isCommentLine';
                }
                field(notes; Rec.Notes)
                {
                    Caption = 'notes';
                }
                field(lastModifiedDateTime; Rec.SystemModifiedAt)
                {
                    Caption = 'lastModifiedDateTime';
                }
            }
        }
    }
}
