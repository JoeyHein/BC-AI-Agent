import httpx, fitz
H={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0'}
base="https://www.sanwa-ss.co.jp/english/files/"
cands=[
 base+"Pas/2_D_Doors.pdf",
 base+"Pas/3_W_Windows.pdf",
 base+"Pas/4_P_Partitions.pdf",
 base+"Pas/5_E_Exterior.pdf",
 base+"Pas/6_G_Garage.pdf",
 base+"Pas/2_Doors.pdf",
 base+"Pas/3_Windows.pdf",
 base+"pdf/doors_products.pdf",
 base+"pdf/window_shutters_doors.pdf",
 base+"pdf/shutter_doors.pdf",
 base+"pdf/building_products.pdf",
 base+"pdf/residential.pdf",
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
