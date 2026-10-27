/// Release one unreleased purchase order.
///
/// api/v2.0 purchaseOrders does not document Microsoft.NAV.release. Its
/// documented bound action is ReceiveAndInvoice. This page adds
/// Microsoft.NAV.release and calls Release Purchase Document. It does not
/// add Reopen, Receive, or Invoice.
///
/// Publish this page, then the portal calls (after the standard action
/// returns 404):
///   POST .../api/opendc/purchasing/v1.0/companies({companyId})/purchaseOrderReleases({systemId})/Microsoft.NAV.release
///
/// The systemId is the purchase order id the standard API already returns.
/// Confirm object IDs 70912 and 70913 are free before publishing.
page 70912 "OPENDC API PO Release"
{
    PageType = API;
    Caption = 'OPENDC Purchase Order Release';
    APIPublisher = 'opendc';
    APIGroup = 'purchasing';
    APIVersion = 'v1.0';
    EntityName = 'purchaseOrderRelease';
    EntitySetName = 'purchaseOrderReleases';
    SourceTable = "Purchase Header";
    SourceTableView = where("Document Type" = const(Order));
    ODataKeyFields = SystemId;
    DelayedInsert = true;
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
                    Caption = 'id';
                    Editable = false;
                }
                field(number; Rec."No.")
                {
                    Caption = 'number';
                    Editable = false;
                }
                field(status; Rec.Status)
                {
                    Caption = 'status';
                    Editable = false;
                }
            }
        }
    }

    [ServiceEnabled]
    procedure release(var ActionContext: WebServiceActionContext)
    var
        ReleasePurchDoc: Codeunit "Release Purchase Document";
    begin
        if Rec.Status = Rec.Status::Released then
            Error('Purchase order %1 is already Released.', Rec."No.");
        if Rec.Status = Rec.Status::"Pending Approval" then
            Error('Purchase order %1 is pending approval and cannot be released from the portal.', Rec."No.");
        if Rec.Status = Rec.Status::"Pending Prepayment" then
            Error('Purchase order %1 is pending prepayment and cannot be released from the portal.', Rec."No.");

        // PerformManualRelease only. There is no Reopen procedure on this page.
        ReleasePurchDoc.PerformManualRelease(Rec);
        ActionContext.SetResultCode(WebServiceActionResultCode::Updated);
    end;
}

permissionset 70913 "OPENDC PO Release"
{
    Assignable = true;
    Caption = 'OPENDC PO Release';
    Permissions =
        tabledata "Purchase Header" = RM,
        tabledata "Purchase Line" = RM,
        codeunit "Release Purchase Document" = X,
        page "OPENDC API PO Release" = X;
}
