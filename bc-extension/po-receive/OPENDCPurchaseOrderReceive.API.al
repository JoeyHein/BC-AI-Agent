/// Receive-only posting for a released purchase order.
///
/// The standard api/v2.0 purchaseOrders entity can set Qty. to Receive
/// (receiveQuantity) but its only bound action is ReceiveAndInvoice, which
/// also posts a purchase invoice. This page adds Microsoft.NAV.receive and
/// sets Invoice to false before Purch.-Post runs.
///
/// Publish this page, then the portal calls:
///   POST .../api/opendc/purchasing/v1.0/companies({companyId})/purchaseOrderReceives({systemId})/Microsoft.NAV.receive
///
/// The systemId is the purchase order id the standard API already returns.
/// Confirm object IDs 70910 and 70911 are free before publishing.
page 70910 "OPENDC API PO Receive"
{
    PageType = API;
    Caption = 'OPENDC Purchase Order Receive';
    APIPublisher = 'opendc';
    APIGroup = 'purchasing';
    APIVersion = 'v1.0';
    EntityName = 'purchaseOrderReceive';
    EntitySetName = 'purchaseOrderReceives';
    SourceTable = "Purchase Header";
    SourceTableView = where("Document Type" = const(Order));
    ODataKeyFields = SystemId;
    DelayedInsert = true;
    Extensible = false;
    InsertAllowed = false;
    DeleteAllowed = false;

    layout
    {
        area(Content)
        {
            repeater(Group)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'id';
                    Editable = false;
                }
                field(number; Rec."No.")
                {
                    Caption = 'number';
                    Editable = false;
                }
                field(vendorShipmentNo; Rec."Vendor Shipment No.")
                {
                    Caption = 'vendorShipmentNo';
                }
                field(status; Rec.Status)
                {
                    Caption = 'status';
                    Editable = false;
                }
                field(lastReceivingNo; Rec."Last Receiving No.")
                {
                    Caption = 'lastReceivingNo';
                    Editable = false;
                }
            }
        }
    }

    [ServiceEnabled]
    procedure receive(var ActionContext: WebServiceActionContext)
    var
        PurchPost: Codeunit "Purch.-Post";
        PurchRcptHeader: Record "Purch. Rcpt. Header";
    begin
        if Rec.Status <> Rec.Status::Released then
            Error('Purchase order %1 is not Released. Release it in Business Central before receiving.', Rec."No.");

        // Receive only. Invoice stays false so this action cannot post a purchase invoice.
        Rec.Receive := true;
        Rec.Invoice := false;
        Rec.Modify(true);

        PurchPost.Run(Rec);

        Rec.Get(Rec."Document Type", Rec."No.");
        PurchRcptHeader.Get(Rec."Last Receiving No.");
        ActionContext.SetObjectType(ObjectType::Page);
        ActionContext.SetObjectId(Page::"Posted Purchase Receipt");
        ActionContext.AddEntityKey(PurchRcptHeader.FieldNo("No."), PurchRcptHeader."No.");
        ActionContext.SetResultCode(WebServiceActionResultCode::Updated);
    end;
}

permissionset 70911 "OPENDC PO Receive"
{
    Assignable = true;
    Caption = 'OPENDC PO Receive';
    Permissions =
        tabledata "Purchase Header" = RM,
        tabledata "Purchase Line" = RM,
        codeunit "Purch.-Post" = X,
        page "OPENDC API PO Receive" = X,
        page "Posted Purchase Receipt" = R;
}
