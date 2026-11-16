/// <summary>
/// Execute the receive API page. Add this on top of the integration user's
/// existing purchase-order permissions, including the rights that user needs
/// to post a receipt in the Business Central client (item ledger and the
/// other tables Purch.-Post writes). This set does not replace those rights
/// and does not grant permission to invoice.
/// </summary>
permissionset 70153 "OPENDC PO Receive"
{
    Caption = 'OPENDC Purchase Order Receive';
    Assignable = true;

    Permissions =
        tabledata "Purchase Header" = RM,
        tabledata "Purchase Line" = RM,
        tabledata "Purch. Rcpt. Header" = R,
        tabledata "Purch. Rcpt. Line" = R,
        codeunit "Release Purchase Document" = X,
        codeunit "Purch.-Post" = X,
        page "OPENDC API PO Receive" = X;
}
