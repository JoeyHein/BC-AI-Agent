/// <summary>
/// Execute the release API page. Add this on top of the integration user's
/// existing purchase-order permissions. Do not use it as that user's only set:
/// Release Purchase Document also needs the tables that user already has in
/// order to create a draft.
/// </summary>
permissionset 70151 "OPENDC PO Release"
{
    Caption = 'OPENDC Purchase Order Release';
    Assignable = true;

    Permissions =
        tabledata "Purchase Header" = RM,
        tabledata "Purchase Line" = R,
        codeunit "Release Purchase Document" = X,
        page "OPENDC API PO Release" = X;
}
