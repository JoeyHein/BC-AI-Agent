/// <summary>
/// Receive selected lines on one purchase order. Does not invoice and does
/// not email the vendor.
///
/// The standard api/v2.0 purchaseOrders page (30066 "APIV2 - Purchase Orders")
/// publishes ReceiveAndInvoice only. That procedure sets Receive and Invoice
/// to true, and a combined post invoices the quantity just received. The page
/// is Extensible = false, so a page extension cannot add a receive-only
/// action. Page 50's posting buttons are not [ServiceEnabled].
///
/// This page is a different entity in the same API group as page 70150
/// "OPENDC API PO Release". Publish both in one extension. A second app
/// cannot own api/opendc/purchasing/v1.0.
///
/// The portal POSTs:
///   /api/opendc/purchasing/v1.0/companies({companyId})/purchaseOrderReceiptPosts({systemId})/Microsoft.NAV.FindReceipt
///   /api/opendc/purchasing/v1.0/companies({companyId})/purchaseOrderReceiptPosts({systemId})/Microsoft.NAV.Receive
///
/// {systemId} is Purchase Header.SystemId, the same id api/v2.0 returns.
/// linesJson is a JSON array of {"lineNo": 10000, "qty": 30}. lineNo is
/// Purchase Line."Line No." (the purchaseOrders API field sequence).
/// Lines omitted from the array are posted with Qty. to Receive = 0.
/// Confirm object IDs 70152 and 70153 are free before publishing.
/// </summary>
page 70152 "OPENDC API PO Receive"
{
    PageType = API;
    Caption = 'OPENDC Purchase Order Receive';
    APIPublisher = 'opendc';
    APIGroup = 'purchasing';
    APIVersion = 'v1.0';
    EntityName = 'purchaseOrderReceiptPost';
    EntitySetName = 'purchaseOrderReceiptPosts';
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
                field(postedReceiptNo; PostedReceiptNo)
                {
                    Caption = 'Posted Receipt No.';
                    Editable = false;
                }
                field(postedReceiptId; PostedReceiptId)
                {
                    Caption = 'Posted Receipt Id';
                    Editable = false;
                }
                field(lastReceivingNo; Rec."Last Receiving No.")
                {
                    Caption = 'Last Receiving No.';
                    Editable = false;
                }
                field(vendorShipmentNo; Rec."Vendor Shipment No.")
                {
                    Caption = 'Vendor Shipment No.';
                    Editable = false;
                }
                field(idempotent; IdempotentReplay)
                {
                    Caption = 'Idempotent';
                    Editable = false;
                }
                field(releasedForReceipt; ReleasedForReceipt)
                {
                    Caption = 'Released For Receipt';
                    Editable = false;
                }
                field(invoiced; ReceiptWasInvoiced)
                {
                    Caption = 'Invoiced';
                    Editable = false;
                }
            }
        }
    }

    /// <summary>
    /// Look up a posted receipt for this order and vendor shipment number.
    /// Does not release, receive, invoice, or email.
    /// </summary>
    [ServiceEnabled]
    [Scope('Cloud')]
    [Caption('Finds a posted purchase receipt by vendor shipment number. Does not post.')]
    procedure FindReceipt(var ActionContext: WebServiceActionContext; vendorShipmentNo: Text)
    var
        PurchRcptHeader: Record "Purch. Rcpt. Header";
        ShipmentNo: Code[35];
    begin
        ReceiptWasInvoiced := false;
        IdempotentReplay := false;
        ReleasedForReceipt := false;
        Clear(PostedReceiptNo);
        Clear(PostedReceiptId);
        ShipmentNo := NormalizeShipmentNo(vendorShipmentNo);
        if ShipmentNo = '' then begin
            SetActionResponse(ActionContext);
            exit;
        end;
        if FindPostedReceipt(Rec."No.", ShipmentNo, PurchRcptHeader) then
            SetReceipt(PurchRcptHeader, true);
        SetActionResponse(ActionContext);
    end;

    /// <summary>
    /// Post a receipt for the lines in linesJson. Invoice is forced false.
    /// No mail codeunit is called. A Draft (BC status Open) order is released
    /// first, because posting requires Released. A repeat with the same
    /// vendor shipment number returns the existing receipt and does not post.
    /// </summary>
    [ServiceEnabled]
    [Scope('Cloud')]
    [Caption('Receives the given quantities. Does not invoice or email the vendor.')]
    procedure Receive(var ActionContext: WebServiceActionContext; vendorShipmentNo: Text; linesJson: Text)
    var
        PurchHeader: Record "Purchase Header";
        PurchRcptHeader: Record "Purch. Rcpt. Header";
        ReleasePurchDoc: Codeunit "Release Purchase Document";
        LineQty: Dictionary of [Integer, Decimal];
        ShipmentNo: Code[35];
    begin
        ReceiptWasInvoiced := false;
        IdempotentReplay := false;
        ReleasedForReceipt := false;
        Clear(PostedReceiptNo);
        Clear(PostedReceiptId);

        ShipmentNo := NormalizeShipmentNo(vendorShipmentNo);
        if (ShipmentNo <> '') and FindPostedReceipt(Rec."No.", ShipmentNo, PurchRcptHeader) then begin
            SetReceipt(PurchRcptHeader, true);
            SetActionResponse(ActionContext);
            exit;
        end;

        ParseLines(linesJson, LineQty);
        PurchHeader.Get(Rec."Document Type", Rec."No.");
        if (PurchHeader.Status <> PurchHeader.Status::Open) and (PurchHeader.Status <> PurchHeader.Status::Released) then
            Error(StatusErr, PurchHeader."No.", PurchHeader.Status);

        // Reject a bad quantity before release, so a refused receipt does not
        // release the order as a side effect.
        CheckQuantities(PurchHeader, LineQty);

        if PurchHeader.Status = PurchHeader.Status::Open then begin
            ReleasePurchDoc.PerformManualRelease(PurchHeader);
            PurchHeader.Get(PurchHeader."Document Type", PurchHeader."No.");
            ReleasedForReceipt := true;
        end;
        if PurchHeader.Status <> PurchHeader.Status::Released then
            Error(StatusErr, PurchHeader."No.", PurchHeader.Status);

        ApplyQuantities(PurchHeader, LineQty);
        if ShipmentNo <> '' then
            PurchHeader.Validate("Vendor Shipment No.", ShipmentNo);
        // Receive only. Purch.-Post with Invoice = false creates a posted
        // purchase receipt and does not create a posted purchase invoice.
        // Qty. to Invoice is left to that codeunit. Forcing it to zero here
        // would stick on the order and block a later invoice in the client.
        PurchHeader.Receive := true;
        PurchHeader.Invoice := false;
        PurchHeader.Ship := false;
        PurchHeader.Modify(true);

        if not PurchHeader.SendToPosting(Codeunit::"Purch.-Post") then
            Error(PostFailedErr, PurchHeader."No.", GetLastErrorText());

        if PurchHeader."Last Receiving No." <> '' then
            PostedReceiptNo := PurchHeader."Last Receiving No.";
        if PurchHeader.Get(PurchHeader."Document Type", PurchHeader."No.") then
            if (PostedReceiptNo = '') and (PurchHeader."Last Receiving No." <> '') then
                PostedReceiptNo := PurchHeader."Last Receiving No.";
        if (ShipmentNo <> '') and FindPostedReceipt(PurchHeader."No.", ShipmentNo, PurchRcptHeader) then
            SetReceipt(PurchRcptHeader, false);
        ReceiptWasInvoiced := false;
        SetActionResponse(ActionContext);
    end;

    local procedure SetReceipt(PurchRcptHeader: Record "Purch. Rcpt. Header"; Replay: Boolean)
    begin
        PostedReceiptNo := PurchRcptHeader."No.";
        PostedReceiptId := PurchRcptHeader.SystemId;
        IdempotentReplay := Replay;
        ReceiptWasInvoiced := false;
    end;

    local procedure FindPostedReceipt(OrderNo: Code[20]; ShipmentNo: Code[35]; var PurchRcptHeader: Record "Purch. Rcpt. Header"): Boolean
    begin
        if (OrderNo = '') or (ShipmentNo = '') then
            exit(false);
        PurchRcptHeader.Reset();
        PurchRcptHeader.SetRange("Order No.", OrderNo);
        PurchRcptHeader.SetRange("Vendor Shipment No.", ShipmentNo);
        exit(PurchRcptHeader.FindFirst());
    end;

    local procedure NormalizeShipmentNo(Raw: Text): Code[35]
    var
        Cleaned: Text;
    begin
        Cleaned := UpperCase(DelChr(Raw, '<>', ' '));
        if Cleaned = '' then
            exit('');
        if StrLen(Cleaned) > MaxStrLen(Rec."Vendor Shipment No.") then
            Error(ShipmentNoLengthErr, MaxStrLen(Rec."Vendor Shipment No."));
        exit(CopyStr(Cleaned, 1, MaxStrLen(Rec."Vendor Shipment No.")));
    end;

    local procedure ParseLines(LinesJson: Text; var LineQty: Dictionary of [Integer, Decimal])
    var
        Items: JsonArray;
        Item: JsonToken;
        Obj: JsonObject;
        LineTok: JsonToken;
        QtyTok: JsonToken;
        LineNo: Integer;
        Qty: Decimal;
    begin
        if DelChr(LinesJson, '<>', ' ') = '' then
            Error(LinesRequiredErr);
        if not Items.ReadFrom(LinesJson) then
            Error(LinesJsonErr);
        foreach Item in Items do begin
            if not Item.IsObject() then
                Error(LinesJsonErr);
            Obj := Item.AsObject();
            if not ReadLineNo(Obj, LineTok) then
                Error(LineNoRequiredErr);
            if not Obj.Get('qty', QtyTok) then
                Error(QtyRequiredErr);
            // lineNo is sent as a JSON integer (Purchase Line "Line No.").
            LineNo := LineTok.AsValue().AsInteger();
            Qty := QtyTok.AsValue().AsDecimal();
            if LineQty.ContainsKey(LineNo) then
                Error(DuplicateLineErr, LineNo);
            if Qty <= 0 then
                Error(QtyPositiveErr, LineNo);
            LineQty.Add(LineNo, Qty);
        end;
        if LineQty.Count() = 0 then
            Error(LinesRequiredErr);
    end;

    local procedure ReadLineNo(Obj: JsonObject; var LineTok: JsonToken): Boolean
    begin
        if Obj.Get('lineNo', LineTok) then
            exit(true);
        exit(Obj.Get('line_no', LineTok));
    end;

    local procedure CheckQuantities(PurchHeader: Record "Purchase Header"; LineQty: Dictionary of [Integer, Decimal])
    var
        PurchLine: Record "Purchase Line";
        Seen: Dictionary of [Integer, Boolean];
        LineKeys: List of [Integer];
        LineNo: Integer;
        LineIndex: Integer;
        Qty: Decimal;
        Outstanding: Decimal;
    begin
        PurchLine.SetRange("Document Type", PurchHeader."Document Type");
        PurchLine.SetRange("Document No.", PurchHeader."No.");
        if PurchLine.FindSet() then
            repeat
                if LineQty.ContainsKey(PurchLine."Line No.") then begin
                    Qty := LineQty.Get(PurchLine."Line No.");
                    Outstanding := OutstandingQty(PurchLine);
                    if Qty > Outstanding then
                        Error(QtyOutstandingErr, PurchHeader."No.", PurchLine."Line No.", Qty, Outstanding);
                    if PurchLine.Type = PurchLine.Type::" " then
                        Error(NotReceivableErr, PurchHeader."No.", PurchLine."Line No.");
                    Seen.Add(PurchLine."Line No.", true);
                end;
            until PurchLine.Next() = 0;
        LineKeys := LineQty.Keys();
        for LineIndex := 1 to LineKeys.Count() do begin
            LineNo := LineKeys.Get(LineIndex);
            if not Seen.ContainsKey(LineNo) then
                Error(UnknownLineErr, PurchHeader."No.", LineNo);
        end;
    end;

    local procedure ApplyQuantities(PurchHeader: Record "Purchase Header"; LineQty: Dictionary of [Integer, Decimal])
    var
        PurchLine: Record "Purchase Line";
        Qty: Decimal;
        Changed: Boolean;
    begin
        PurchLine.SetRange("Document Type", PurchHeader."Document Type");
        PurchLine.SetRange("Document No.", PurchHeader."No.");
        if PurchLine.FindSet(true) then
            repeat
                Changed := false;
                if LineQty.ContainsKey(PurchLine."Line No.") then begin
                    Qty := LineQty.Get(PurchLine."Line No.");
                    if Qty > OutstandingQty(PurchLine) then
                        Error(QtyOutstandingErr, PurchHeader."No.", PurchLine."Line No.", Qty, OutstandingQty(PurchLine));
                    PurchLine.Validate("Qty. to Receive", Qty);
                    Changed := true;
                end else
                    if PurchLine."Qty. to Receive" <> 0 then begin
                        PurchLine.Validate("Qty. to Receive", 0);
                        Changed := true;
                    end;
                if Changed then
                    PurchLine.Modify(true);
            until PurchLine.Next() = 0;
    end;

    local procedure OutstandingQty(PurchLine: Record "Purchase Line"): Decimal
    var
        Outstanding: Decimal;
    begin
        Outstanding := PurchLine.Quantity - PurchLine."Quantity Received";
        if Outstanding < 0 then
            Outstanding := 0;
        exit(Outstanding);
    end;

    local procedure SetActionResponse(var ActionContext: WebServiceActionContext)
    begin
        ActionContext.SetObjectType(ObjectType::Page);
        ActionContext.SetObjectId(Page::"OPENDC API PO Receive");
        ActionContext.AddEntityKey(Rec.FieldNo(SystemId), Rec.SystemId);
        ActionContext.SetResultCode(WebServiceActionResultCode::Updated);
    end;

    var
        PostedReceiptNo: Code[20];
        PostedReceiptId: Guid;
        IdempotentReplay: Boolean;
        ReleasedForReceipt: Boolean;
        ReceiptWasInvoiced: Boolean;
        LinesRequiredErr: Label 'RECEIVE:lines At least one line quantity is required. Nothing was posted.';
        LinesJsonErr: Label 'RECEIVE:lines linesJson must be a JSON array of lineNo and qty. Nothing was posted.';
        LineNoRequiredErr: Label 'RECEIVE:lines Each line needs lineNo. Nothing was posted.';
        QtyRequiredErr: Label 'RECEIVE:lines Each line needs qty. Nothing was posted.';
        QtyPositiveErr: Label 'RECEIVE:qty Line %1 quantity must be greater than zero. Nothing was posted.';
        DuplicateLineErr: Label 'RECEIVE:lines Line %1 is listed more than once. Nothing was posted.';
        QtyOutstandingErr: Label 'RECEIVE:qty Purchase order %1 line %2 quantity %3 exceeds outstanding %4. Nothing was posted.';
        UnknownLineErr: Label 'RECEIVE:line Purchase order %1 has no line %2. Nothing was posted.';
        NotReceivableErr: Label 'RECEIVE:line Purchase order %1 line %2 cannot be received. Nothing was posted.';
        StatusErr: Label 'RECEIVE:status Purchase order %1 is %2 and cannot be received. Release is only attempted for an open order. Nothing was posted.';
        ShipmentNoLengthErr: Label 'RECEIVE:lines Vendor shipment number is longer than %1 characters. Nothing was posted.';
        PostFailedErr: Label 'RECEIVE:post Purchase order %1 was not received. %2';
}
