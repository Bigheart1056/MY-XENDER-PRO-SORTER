from concurrent.futures import ThreadPoolExecutor
import re
import dns.resolver
import pandas as pd
import streamlit as st

st.set_page_config(page_title='Lead Email Sorter', page_icon='📧', layout='wide')
st.title('📧 Lead Email Provider & Pre-Bounce Sorter')

FREE = {
    'gmail.com',
    'googlemail.com',
    'yahoo.com',
    'yahoo.co.uk',
    'ymail.com',
    'hotmail.com',
    'hotmail.co.uk',
    'outlook.com',
    'live.com',
    'msn.com',
    'icloud.com',
    'me.com',
    'mac.com',
    'aol.com',
    'protonmail.com',
    'proton.me',
    'zoho.com',
    'gmx.com',
    'mail.com',
}
DISP = {
    'mailinator.com',
    'temp-mail.org',
    'tempmail.com',
    '10minutemail.com',
    'guerrillamail.com',
    'yopmail.com',
    'throwawaymail.com',
    'sharklasers.com',
    'getnada.com',
    'trashmail.com',
    'fakeinbox.com',
    'dispostable.com',
    'maildrop.cc',
}
TYPO = {
    'gnail.com',
    'gmal.com',
    'gamil.com',
    'gmial.com',
    'gmail.co',
    'gmail.cm',
    'yaho.com',
    'yahooo.com',
    'yhoo.com',
    'yahoo.co',
    'hotmal.com',
    'hotmai.com',
    'hotmial.com',
    'hotmail.co',
    'outlok.com',
    'outllok.com',
    'outlook.co',
    'iclod.com',
    'icoud.com',
}
PARK = {
    'parking',
    'sedoparking',
    'bodis',
    'above.com',
    'hugedomains',
    'afternic',
    'dan.com',
    'uniregistry',
    'localhost',
}
ROLE = {
    'info',
    'sales',
    'support',
    'admin',
    'contact',
    'hello',
    'office',
    'team',
    'billing',
    'hr',
    'jobs',
    'marketing',
    'noreply',
    'no-reply',
    'postmaster',
    'abuse',
    'webmaster',
    'hostmaster',
    'privacy',
    'legal',
    'security',
    'enquiries',
    'inquiries',
}
RX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')


def is_valid(e):
  e = str(e).strip().lower()
  return bool(e and '..' not in e and ' ' not in e and RX.match(e))


def get_gw(mx):
  if 'mimecast' in mx:
    return 'Mimecast'
  if 'pphosted' in mx or 'proofpoint' in mx:
    return 'Proofpoint'
  if 'barracuda' in mx:
    return 'Barracuda'
  if 'iphmx' in mx or 'cisco' in mx:
    return 'Cisco IronPort'
  return 'None'


def analyze_dom(d):
  if not d or '.' not in d:
    return ('Invalid / Syntax Error', 'None', 'Hard Bounce (Syntax)')
  if d in TYPO:
    return ('Invalid / Typo Domain', 'None', 'Hard Bounce (Domain Typo)')
  if d in DISP:
    return ('Disposable / Burner', 'None', 'Hard Bounce (Disposable)')
  if d in FREE:
    return ('Personal / Free Email', 'None', 'Low Risk (Consumer)')
  try:
    mx_rec = dns.resolver.resolve(d, 'MX', lifetime=3)
    hosts = [str(r.exchange).lower().rstrip('.') for r in mx_rec]
    mx = ' '.join(hosts)
    if not hosts or hosts == [''] or hosts == ['.']:
      return ('Invalid / No MX', 'None', 'Hard Bounce (Null MX)')
    if any(k in mx for k in PARK):
      return ('Invalid / Parked Domain', 'None', 'Hard Bounce (Parked)')
    gw = get_gw(mx)
    if 'google.com' in mx or 'googlemail.com' in mx:
      return ('Google Workspace', gw, 'Safe / Valid MX')
    if 'outlook.com' in mx:
      return ('Microsoft 365', gw, 'Medium Risk (Catch-All Possible)')
    txt = ''
    try:
      txt = ' '.join([
          str(r).lower() for r in dns.resolver.resolve(d, 'TXT', lifetime=3)
      ])
    except Exception:
      pass
    if '"v=spf1 -all"' in txt or "'v=spf1 -all'" in txt:
      return ('Invalid / Non-Sending Domain', 'None', 'Hard Bounce (SPF -all)')
    if '_://google.com' in txt:
      return ('Google Workspace', gw, 'Safe / Valid MX')
    if '://outlook.com' in txt:
      return ('Microsoft 365', gw, 'Medium Risk (Catch-All Possible)')
    return ('Other', gw, 'Safe / Valid MX')
  except Exception:
    return ('Invalid / No MX', 'None', 'Hard Bounce (Dead Domain)')


def parse_parts(e, br):
  if not is_valid(e):
    return (br, '')
  loc, _ = str(e).strip().lower().split('@', 1)
  pts = re.split(r'[._\-0-9]+', loc)
  fst = next((p for p in pts if p), '')
  rk = (
      'High Risk (Role / Generic Address)'
      if (loc in ROLE or fst in ROLE) and 'Hard Bounce' not in br
      else br
  )
  fn = (
      fst.capitalize()
      if (len(pts) >= 2 and len(fst) >= 2 and fst not in ROLE)
      else ''
  )
  return (rk, fn)


def get_comp(d):
  if not d or d in FREE or d in DISP or d in TYPO or '.' not in d:
    return ''
  m, _ = d.split('.', 1)
  return m.replace('-', ' ').title()


if 'sorted_df' not in st.session_state:
  st.session_state.sorted_df = None
if 'last_id' not in st.session_state:
  st.session_state.last_id = None

up = st.file_uploader('Upload CSV or TXT', type=['csv', 'txt'])
if up is not None:
  fid = f'{up.name}_{up.size}'
  if st.session_state.last_id != fid:
    st.session_state.sorted_df = None
    st.session_state.last_id = fid
  if up.name.lower().endswith('.txt'):
    raw = pd.DataFrame({
        'email': [
            l.decode('utf-8', errors='ignore').strip()
            for l in up.readlines()
            if l.strip()
        ]
    })
    ecol = 'email'
  else:
    raw = pd.read_csv(up)
    idx = next((i for i, c in enumerate(raw.columns) if 'email' in c.lower()), 0)
    ecol = st.selectbox('Select email column:', raw.columns, index=idx)

  if st.button('Clean, Sort & Score Bounce Risk', type='primary'):
    with st.spinner('Analyzing leads...'):
      df = raw.copy()
      df[ecol] = df[ecol].astype(str).str.strip()
      df = df.drop_duplicates(subset=[ecol]).copy()
      df['_v'] = df[ecol].apply(is_valid)
      df['_d'] = df.apply(
          lambda r: r[ecol].split('@', 1)[-1].lower() if r['_v'] else '', axis=1
      )
      udoms = [d for d in df['_d'].unique() if d]
      with ThreadPoolExecutor(max_workers=25) as ex:
        dmap = dict(zip(udoms, ex.map(analyze_dom, udoms)))
      provs, gws, brisks = [], [], []
      for v, d in zip(df['_v'], df['_d']):
        p, g, r = (
            dmap.get(d, ('Invalid / No MX', 'None', 'Hard Bounce (Dead)'))
            if v
            else ('Invalid / Syntax Error', 'None', 'Hard Bounce (Syntax)')
        )
        provs.append(p)
        gws.append(g)
        brisks.append(r)
      frisks, fnames = [], []
      for e, br in zip(df[ecol], brisks):
        fr, fn = parse_parts(e, br)
        frisks.append(fr)
        fnames.append(fn)
      df['Provider'], df['Security_Gateway'], df['Bounce_Risk'] = (
          provs,
          gws,
          frisks,
      )
      df['Extracted_First_Name'], df['Extracted_Company'] = (
          fnames,
          df['_d'].apply(get_comp),
      )
      df.drop(columns=['_v', '_d'], inplace=True)
      st.session_state.sorted_df = df

if st.session_state.sorted_df is not None:
  df = st.session_state.sorted_df
  st.success(f'Done! Processed {len(df):,} unique rows.')
  cnt = df['Provider'].value_counts()
  c1, c2, c3, c4 = st.columns(4)
  c1.metric('Google Workspace', cnt.get('Google Workspace', 0))
  c2.metric('Microsoft 365', cnt.get('Microsoft 365', 0))
  c3.metric('Personal / Free', cnt.get('Personal / Free Email', 0))
  c4.metric('Other B2B', cnt.get('Other', 0))

  r1, r2, r3, r4 = st.columns(4)
  hb = df[df['Bounce_Risk'].str.startswith('Hard Bounce')]
  rr = df[df['Bounce_Risk'].str.startswith('High Risk')]
  r1.metric('Hard Bounces Caught', len(hb))
  r2.metric('Role / Generic Risk', len(rr))
  r3.metric('Domain Typos', cnt.get('Invalid / Typo Domain', 0))
  r4.metric(
      'Parked / Dead Domains',
      cnt.get('Invalid / No MX', 0) + cnt.get('Invalid / Parked Domain', 0),
  )

  f1, f2 = st.columns(2)
  ex_gw = f1.checkbox(
      'Exclude Mimecast / Proofpoint / Barracuda from Google & Microsoft',
      value=False,
  )
  ex_rl = f2.checkbox(
      'Exclude Role/Generic (info@, sales@) from Google & Microsoft', value=True
  )

  g_df = df[df['Provider'] == 'Google Workspace']
  m_df = df[df['Provider'] == 'Microsoft 365']
  if ex_gw:
    g_df = g_df[g_df['Security_Gateway'] == 'None']
    m_df = m_df[m_df['Security_Gateway'] == 'None']
  if ex_rl:
    g_df = g_df[~g_df['Bounce_Risk'].str.startswith('High Risk')]
    m_df = m_df[~m_df['Bounce_Risk'].str.startswith('High Risk')]
  p_df = df[df['Provider'] == 'Personal / Free Email']
  o_df = df[df['Provider'] == 'Other']

  d1, d2, d3, d4, d5, d6 = st.columns(6)
  d1.download_button(
      '⬇️ All Rows',
      df.to_csv(index=False).encode('utf-8'),
      'all_leads.csv',
      'text/csv',
      key='d1',
  )
  d2.download_button(
      f'⬇️ Google ({len(g_df)})',
      g_df.to_csv(index=False).encode('utf-8'),
      'google.csv',
      'text/csv',
      key='d2',
  )
  d3.download_button(
      f'⬇️ Microsoft ({len(m_df)})',
      m_df.to_csv(index=False).encode('utf-8'),
      'microsoft.csv',
      'text/csv',
      key='d3',
  )
  d4.download_button(
      f'⬇️ Personal ({len(p_df)})',
      p_df.to_csv(index=False).encode('utf-8'),
      'personal.csv',
      'text/csv',
      key='d4',
  )
  d5.download_button(
      f'⬇️ Other ({len(o_df)})',
      o_df.to_csv(index=False).encode('utf-8'),
      'other.csv',
      'text/csv',
      key='d5',
  )
  d6.download_button(
      f'⬇️ Hard Bounces ({len(hb)})',
      hb.to_csv(index=False).encode('utf-8'),
      'hard_bounces.csv',
      'text/csv',
      key='d6',
  )

  t1, t2, t3 = st.tabs([
      f'All Leads ({len(df)})',
      f'🚫 Hard Bounces ({len(hb)})',
      f'⚠️ Role Risk ({len(rr)})',
  ])
  with t1:
    st.dataframe(df.head(50), use_container_width=True)
  with t2:
    st.dataframe(hb, use_container_width=True)
  with t3:
    st.dataframe(rr, use_container_width=True)
