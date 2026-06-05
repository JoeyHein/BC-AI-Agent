import httpx, fitz
H={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0'}
base="https://www.sanwa-ss.co.jp/english/files/"
cands=[
 base+"pdf/steel_doors.pdf",
 base+"pdf/doors.pdf",
 base+"pdf/partitions.pdf",
 base+"pdf/exterior_products.pdf",
 base+"pdf/garage_products.pdf",
 base+"pdf/fire_shutters.pdf",
 base+"pdf/high_speed_door.pdf",
 base+"pdf/high_speed_doors.pdf",
 base+"pdf/sheet_shutter.pdf",
 base+"Pas/2_S_ShutterRelated_Products.pdf",
 base+"Pas/1_D_Doors.pdf",
 base+"Pas/1_D_HingeDoors.pdf",
 base+"pdf/hinge_doors.pdf",
 base+"pdf/window_products.pdf",
 base+"pdf/company_profile.pdf",
 "https://www.sanwa-ss.co.jp/english/info/eng_20160705md.pdf",
]
for u in cands:
    try:
        d=httpx.get(u,follow_redirects=True,timeout=40,headers=H,verify=False).content
        if d[:1024].find(b'%PDF')>=0 and b'%%EOF' in d[-4096:] and len(d)>40000:
            doc=fitz.open(stream=d,filetype='pdf');n=doc.page_count;doc.close()
            print('OK',n,u)
        else:
            print('BAD',len(d),u)
    except Exception as e:
        print('ERR',str(e)[:50],u)
