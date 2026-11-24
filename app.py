from concurrent.futures import ThreadPoolExecutor
import re
import dns.resolver
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title='Lead Email Provider & Pre-Bounce Sorter',
    page_icon='📧',
    layout='wide',
)
st.title('📧 Lead Email Provider & Pre-Bounce Sorter')
st.write(
    'Sort B2B providers, detect security gateways, catch typos/parked domains,'
    ' and score bounce risk.'
)

FREE_DOMAINS = {
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
DISPOSABLE_DOMAINS = {
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
TYPO_DOMAINS = {
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
PARKED_KEYWORDS = {
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
ROLE_PREFIXES = {
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
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')


def is_valid_syntax(email):
  e = str(email).strip().lower()
  return bool(e and '..' not in e and ' ' not in e and EMAIL_REGEX.match(e))


def detect_gateway(mx):
  if 'mimecast' in mx:
    return 'Mimecast'
  if 'pphosted' in mx or 'proofpoint' in mx:
    return 'Proofpoint'
  if 'barracuda' in mx:
    return 'Barracuda'
  if 'iphmx' in mx or 'cisco' in mx:
    return 'Cisco IronPort'
  return 'None'


def analyze_domain(domain):
  if not domain or '.' not in domain:
    return ('Invalid / Syntax Error', 'None', 'Hard Bounce (Syntax)')
  if domain in TYPO_DOMAINS:
    return ('Invalid / Typo Domain', 'None', 'Hard Bounce (Domain Typo)')
  if domain in DISPOSABLE_DOMAINS:
    return ('Disposable / Burner', 'None', 'Hard Bounce (Disposable)')
  if domain in FREE_DOMAINS:
    return ('Personal / Free Email', 'None', 'Low Risk (Consumer)')

  try:
    mx_records = dns.resolver.resolve(domain, 'MX', lifetime=3)
    mx_hosts = [str(r.exchange).lower().rstrip('.') for r in mx_records]
    mx_str = ' '.join(mx_hosts)

    if not mx_hosts or mx_hosts == [''] or mx_hosts == ['.']:
      return ('Invalid / No MX', 'None', 'Hard Bounce (Null MX)')
    if any(kw in mx_str for kw in PARKED_KEYWORDS):
      return ('Invalid / Parked Domain', 'None', 'Hard Bounce (Parked)')

    gw = detect_gateway(mx_str)
    if 'google.com' in mx_str or 'googlemail.com' in mx_str:
      return ('Google Workspace', gw, 'Safe / Valid MX')
    if 'outlook.com' in mx_str:
      return ('Microsoft 365', gw, 'Medium Risk (Catch-All Possible)')

    txt_str = ''
    try:
      txt_records = dns.resolver.resolve(domain, 'TXT', lifetime=3)
      txt_str = ' '.join([str(r).lower() for r in txt_records])
    except Exception:
      pass

    if '"v=spf1 -all"' in txt_str or "'v=spf1 -all'" in txt_str:
      return ('Invalid / Non-Sending Domain', 'None', 'Hard Bounce (SPF -all)')
    if '_://google.com' in txt_str:
      return ('Google Workspace', gw, 'Safe / Valid MX')
    if '://outlook.com' in txt_str:
      return ('Microsoft 365', gw, 'Medium Risk (Catch-All Possible)')

    return ('Other', gw, 'Safe / Valid MX')
  except Exception:
    return ('Invalid / No MX', 'None', 'Hard Bounce (Dead Domain)')


def parse_email_parts(email, base_risk):
  if not is_valid_syntax(email):
    return (base_risk, '')
  local, _ = str(email).strip().lower().split('@', 1)
  parts = re.split(r'[._\-0-9]+', local)
  first = next((p for p in parts if p), '')
  risk = (
      'High Risk (Role / Generic Address)'
      if (local in ROLE_PREFIXES or first in ROLE_PREFIXES)
      and 'Hard Bounce' not in base_risk
      else base_risk
  )
  fname = (
      first.capitalize()
      if (len(parts) >= 2 and len(first) >= 2 and first not in ROLE_PREFIXES)
      else ''
  )
  return (risk, fname)


def extract_company(domain):
  if (
      not domain
      or domain in FREE_DOMAINS
      or domain in DISPOSABLE_DOMAINS
      or domain in TYPO_DOMAINS
      or '.' not in domain
  ):
    return ''
  main_part, _ = domain.split('.', 1)
  return main_part.replace('-', ' ').title()


if 'sorted_df' not in st.session_state:
  st.session_state.sorted_df = None
if 'last_file_id' not in st.session_state:
  st.session_state.last_file_id = None

uploaded_file = st.file_uploader(
    'Upload your leads file (CSV or TXT)', type=['csv', 'txt']
)

if uploaded_file is not None:
  file_id = f'{uploaded_file.name}_{uploaded_file.size}'
  if st.session_state.last_file_id != file_id:
    st.session_state.sorted_df = None
    st.session_state.last_file_id = file_id

  if uploaded_file.name.lower().endswith('.txt'):
    lines = [
        line.decode('utf-8', errors='ignore').strip()
        for line in uploaded_file.readlines()
    ]
    raw_df = pd.DataFrame({'email': [l for l in lines if l]})
    email_col = 'email'
  else:
    raw_df = pd.read_csv(uploaded_file)
    default_idx = next(
        (i for i, col in enumerate(raw_df.columns) if 'email' in col.lower()), 0
    )
    email_col = st.selectbox(
        'Select email column:', raw_df.columns, index=default_idx
    )

  if st.button('Clean, Sort & Score Bounce Risk', type='primary'):
    with st.spinner(
        'Checking syntax, typos, parked domains, MX/SPF, and role addresses...'
    ):
      df = raw_df.copy()
      df[email_col] = df[email_col].astype(str).str.strip()
      df = df.drop_duplicates(subset=[email_col]).copy()

      df['_valid'] = df[email_col].apply(is_valid_syntax)
      df['_domain'] = df.apply(
          lambda r: r[email_col].split('@', 1)[-1].lower()
          if r['_valid']
          else '',
          axis=1,
      )
      unique_domains = [d for d in df['_domain'].unique() if d]

      with ThreadPoolExecutor(max_workers=25) as ex:
        dom_map = dict(
            zip(unique_domains, ex.map(analyze_domain, unique_domains))
        )

      providers, gateways, base_risks = [], [], []
      for valid, dom in zip(df['_valid'], df['_domain']):
        if not valid:
          p, g, r = ('Invalid / Syntax Error', 'None', 'Hard Bounce (Syntax)')
        else:
          p, g, r = dom_map.get(
              dom, ('Invalid / No MX', 'None', 'Hard Bounce (Dead Domain)')
          )
        providers.append(p)
        gateways.append(g)
        base_risks.append(r)

      final_risks, first_names = [], []
      for email, br in zip(df[email_col], base_risks):
        fr, fn = parse_email_parts(email, br)
        final_risks.append(fr)
        first_names.append(fn)

      df['Provider'] = providers
      df['Security_Gateway'] = gateways
      df['Bounce_Risk'] = final_risks
      df['Extracted_First_Name'] = first_names
      df['Extracted_Company'] = df['_domain'].apply(extract_company)
      df.drop(columns=['_valid', '_domain'], inplace=True)
      st.session_state.sorted_df = df

if st.session_state.sorted_df is not None:
  df = st.session_state.sorted_df
  st.success(f'Done! Processed {len(df):,} unique rows.')
  counts = df['Provider'].value_counts()

  st.subheader('Clean Leads Breakdown')
  c1, c2, c3, c4 = st.columns(4)
  c1.metric('Google Workspace', counts.get('Google Workspace', 0))
  c2.metric('Microsoft 365', counts.get('Microsoft 365', 0))
  c3.metric('Personal / Free', counts.get('Personal / Free Email', 0))
  c4.metric('Other B2B', counts.get('Other', 0))

  st.subheader('Pre-Bounce & Risk Breakdown')
  r1, r2, r3, r4 = st.columns(4)
  hard_bounces = df[df['Bounce_Risk'].str.startswith('Hard Bounce')]
  role_risks = df[df['Bounce_Risk'].str.startswith('High Risk')]
  r1.metric('Hard Bounces Caught', len(hard_bounces))
  r2.metric('Role / Generic Risk', len(role_risks))
  r3.metric('Domain Typos Caught', counts.get('Invalid / Typo Domain', 0))
  r4.metric(
      'Parked / Dead Domains',
      counts.get('Invalid / No MX', 0)
      + counts.get('Invalid / Parked Domain', 0),
  )
    
  st.subheader('Download Your Segmented Lists')
  f1, f2 = st.columns(2)
  exclude_gw = f1.checkbox(
      'Exclude Mimecast / Proofpoint / Barracuda from Google & Microsoft'
      ' downloads',
      value=False,
  )
  exclude_roles = f2.checkbox(
      'Exclude Role/Generic addresses (info@, sales@, admin@) from Google &'
      ' Microsoft downloads',
      value=True,
  )

  g_df = df[df['Provider'] == 'Google Workspace']
  m_df = df[df['Provider'] == 'Microsoft 365']
  if exclude_gw:
    g_df = g_df[g_df['Security_Gateway'] == 'None']
    m_df = m_df[m_df['Security_Gateway'] == 'None']
  if exclude_roles:
    g_df = g_df[~g_df['Bounce_Risk'].str.startswith('High Risk')]
    m_df = m_df[~m_df['Bounce_Risk'].str.startswith('High Risk')]

  p_df = df[df['Provider'] == 'Personal / Free Email']
  o_df = df[df['Provider'] == 'Other']

  d1, d2, d3, d4, d5, d6 = st.columns(6)
  d1.download_button(
      '⬇️ All Rows',
      df.to_csv(index=False).encode('utf-8'),
      'all_processed_leads.csv',
      'text/csv',
      key='dl_all',
  )
  d2.download_button(
      f'⬇️ Google ({len(g_df)})',
