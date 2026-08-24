/// <summary>
/// Read-only API over the LIVE per-line picking checklist — what's still
/// outstanding to pick, right now, for each open sales order.
///
/// This is DIFFERENT from "Picking Selection" (pickingQueue, page 70136),
/// which is order-level queue state (who's picking it, what status) with no
/// item detail. "Picking Entry" is the actual line-by-line checklist: item,
/// order qty, qty already picked, remaining = outstandingQuantity - qtyPicked.
///
/// Transient like Picking Selection — ArchiveAndCleanup clears these rows on
/// post. For posted/historical picking lines use postedPickingLines (page
/// 70140) instead; that carries Sales Order No. too but only after the
/// order has shipped.
/// </summary>
page 70141 "Upwardor API Picking Entry"
{
    PageType = API;
    Caption = 'Picking Entry';
    APIPublisher = 'upwardor';
    APIGroup = 'picking';
    APIVersion = 'v1.0';
    EntityName = 'pickingEntry';
    EntitySetName = 'pickingEntries';
    SourceTable = "Picking Entry";
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
                field(salesLineNo; Rec."Sales Line No.")
                {
                    Caption = 'salesLineNo';
                }
                field(lineNo; Rec."Line No. 2")
                {
                    Caption = 'lineNo';
                }
                field(customerNo; Rec."Customer No.")
                {
                    Caption = 'customerNo';
                }
                field(customerName; Rec."Customer Name")
                {
                    Caption = 'customerName';
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
                field(qtyPerUnitOfMeasure; Rec."Qty. per Unit of Measure")
                {
                    Caption = 'qtyPerUnitOfMeasure';
                }
                field(outstandingQuantity; Rec."Outstanding Quantity")
                {
                    Caption = 'outstandingQuantity';
                }
                field(qtyPicked; Rec."Qty. Picked")
                {
                    Caption = 'qtyPicked';
                }
                field(isCommentLine; Rec."Is Comment Line")
                {
                    Caption = 'isCommentLine';
                }
                field(pickerName; Rec."Picker Name")
                {
                    Caption = 'pickerName';
                }
                field(notes; Rec.Notes)
                {
                    Caption = 'notes';
                }
                field(orderComments; Rec."Order Comments")
                {
                    Caption = 'orderComments';
                }
                field(lastModifiedDateTime; Rec.SystemModifiedAt)
                {
                    Caption = 'lastModifiedDateTime';
                }
            }
        }
    }
}
