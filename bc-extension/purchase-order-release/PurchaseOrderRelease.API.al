/// <summary>
/// Release one purchase order. The standard api/v2.0 purchaseOrders page
/// (30066 "APIV2 - Purchase Orders") publishes ReceiveAndInvoice only, and
/// that page is Extensible = false. Page 50's Release button is not
/// [ServiceEnabled], so publishing it as the PurchaseOrder web service
/// (already used for Vendor Order No.) does not expose a release action.
///
/// The portal POSTs:
///   /api/opendc/purchasing/v1.0/companies({companyId})/purchaseOrders({systemId})/Microsoft.NAV.Release
///
/// {systemId} is Purchase Header.SystemId, the same id api/v2.0 returns.
/// Confirm the object IDs are free in Upwardor_BC_Repos before publishing.
/// </summary>
page 70150 "OPENDC API PO Release"
{
    PageType = API;
    Caption = 'OPENDC Purchase Order Release';
    APIPublisher = 'opendc';
    APIGroup = 'purchasing';
    APIVersion = 'v1.0';
    EntityName = 'purchaseOrder';
    EntitySetName = 'purchaseOrders';
    SourceTable = "Purchase Header";
    SourceTableView = where("Document Type" = const(Order));
    ODataKeyFields = SystemId;
    Extensible = false;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;

    layout
    {
        area(Content)
        {
            repeater(Group)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'Id';
                    Editable = false;
                }
                field(number; Rec."No.")
                {
                    Caption = 'Number';
                    Editable = false;
                }
                field(status; Rec.Status)
                {
                    Caption = 'Status';
                    Editable = false;
                }
                field(vendorNumber; Rec."Buy-from Vendor No.")
                {
                    Caption = 'Vendor Number';
                    Editable = false;
                }
            }
        }
    }

    [ServiceEnabled]
    [Scope('Cloud')]
    [Caption('Releases the purchase order. Does not receive or invoice it.')]
    procedure Release(var ActionContext: WebServiceActionContext)
    var
        ReleasePurchDoc: Codeunit "Release Purchase Document";
    begin
        if Rec.Status = Rec.Status::Released then
            Error(AlreadyReleasedErr, Rec."No.");
        ReleasePurchDoc.PerformManualRelease(Rec);
        Rec.Get(Rec."Document Type", Rec."No.");
        ActionContext.SetObjectType(ObjectType::Page);
        ActionContext.SetObjectId(Page::"OPENDC API PO Release");
        ActionContext.AddEntityKey(Rec.FieldNo(SystemId), Rec.SystemId);
        ActionContext.SetResultCode(WebServiceActionResultCode::Updated);
    end;

    var
        AlreadyReleasedErr: Label 'Purchase order %1 is already released.';
}
