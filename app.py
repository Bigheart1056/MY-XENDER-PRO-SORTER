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
    ' and score bounce risk—100% free without API keys.'
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

PARKED_MX_KEYWORDS = {
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
  email = str(email).strip().lower()
  if not email or '..' in email or ' ' in email:
    return False
  return bool(EMAIL_REGEX.match(email))


def detect_gateway(mx_string):
  if 'mimecast' in mx_string:
    return 'Mimecast'
  elif 'pphosted' in mx_string or 'proofpoint' in mx_string:
    return 'Proofpoint'
  elif 'barracuda' in mx_string:
    return 'Barracuda'
  elif 'iphmx' in mx_string or 'cisco' in mx_string:
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
    mx_string = ' '.join(mx_hosts)

    # Check Null MX (RFC 7505: domain explicitly accepts no email)
    if not mx_hosts or mx_hosts == [''] or mx_hosts == ['.']:
      return ('Invalid / No MX', 'None', 'Hard Bounce (Null MX)')

    # Check Parked Domains
    if any(kw in mx_string for kw in PARKED_MX_KEYWORDS):
      return ('Invalid / Parked Domain', 'None', 'Hard Bounce (Parked)')

    gateway = detect_gateway(mx_string)

    if 'google.com' in mx_string or 'googlemail.com' in mx_string:
      return ('Google Workspace', gateway, 'Safe / Valid MX')
    elif 'outlook.com' in mx_string:
      return ('Microsoft 365', gateway, 'Medium Risk (Catch-All Possible)')

    # Fallback: Check SPF (TXT) records
    txt_string = ''
    try:
      txt_records = dns.resolver.resolve(domain, 'TXT', lifetime=3)
      txt_string = ' '.join([str(r).lower() for r in txt_records])
    except Exception:
      pass

    # Check if domain strictly sends/receives zero email ("v=spf1 -all")
    if '"v=spf1 -all"' in txt_string or "'v=spf1 -all'" in txt_string:
      return ('Invalid / Non-Sending Domain', 'None', 'Hard Bounce (SPF -all)')

    if '_://google.com' in txt_string:
      return ('Google Workspace', gateway, 'Safe / Valid MX')
    elif '://outlook.com' in txt_string:
      return ('Microsoft 365', gateway, 'Medium Risk (Catch-All Possible)')

    return ('Other', gateway, 'Safe / Valid MX')
  except Exception:
    return ('Invalid / No MX', 'None', 'Hard Bounce (Dead Domain)')


def get_prefix_risk(email, base_risk):
  if 'Hard Bounce' in base_risk:
    return base_risk
  try:
    local = str(email).split('@').strip().lower()
    clean_local = re.split(r'[._\-0-9]+', local)
    if local in ROLE_PREFIXES or clean_local in ROLE_PREFIXES:
      return 'High Risk (Role / Generic Address)'
    return base_risk
  except Exception:
    return base_risk


def extract_first_name(email):
  try:
    if not is_valid_syntax(email):
      return ''
    local = str(email).split('@').strip().lower()
    parts = re.split(r'[._\-0-9]+', local)
    first_part = parts if parts else ''
    if (
        len(parts) >= 2
        and len(first_part) >= 2
        and first_part not in ROLE_PREFIXES
    ):
      return first_part.capitalize()
    return ''
  except Exception:
    return ''


def extract_company(domain):
  try:
    if (
        not domain
        or domain in FREE_DOMAINS
        or domain in DISPOSABLE_DOMAINS
        or domain in TYPO_DOMAINS
        or '.' not in domain
    ):
      return ''
    name = domain.split('.')
    return name.replace('-', ' ').title()
  except Exception:
    return ''


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
        'Select which column contains your email addresses:',
        raw_df.columns,
        index=default_idx,
    )

  if st.button('Clean, Sort & Score Bounce Risk', type='primary'):
    with st.spinner(
        'Running syntax, typo, parked domain, MX/SPF, and role-address'
        ' checks...'
    ):
      df = raw_df.copy()
      df[email_col] = df[email_col].astype(str).str.strip()
      df = df.drop_duplicates(subset=[email_col]).copy()

      df['_valid_syntax'] = df[email_col].apply(is_valid_syntax)
      df['_domain'] = df.apply(
          lambda row: row[email_col].split('@')[-1].lower()
          if row['_valid_syntax']
          else '',
          axis=1,
      )

      unique_domains = [d for d in df['_domain'].unique() if d]

      with ThreadPoolExecutor(max_workers=25) as executor:
        domain_results = dict(
            zip(unique_domains, executor.map(analyze_domain, unique_domains))
        )

      def map_results(row):
        if not row['_valid_syntax']:
          return ('Invalid / Syntax Error', 'None', 'Hard Bounce (Syntax)')
        return domain_results.get(
            row['_domain'],
            ('Invalid / No MX', 'None', 'Hard Bounce (Dead Domain)'),
        )

      mapped = df.apply(map_results, axis=1)
      df['Provider'] = [m for m in mapped]
      df['Security_Gateway'] = [m for m in mapped]
      base_risks = [m for m in mapped]

      df['Bounce_Risk'] = [
          get_prefix_risk(email, risk)
          for email, risk in zip(df[email_col], base_risks)
      ]
      df['Extracted_First_Name'] = df[email_col].apply(extract_first_name)
      df['Extracted_Company'] = df['_domain'].apply(extract_company)

      df.drop(columns=['_valid_syntax', '_domain'], inplace=True)
      st.session_state.sorted_df = df

if st.session_state.sorted_df is not None:
  df = st.session_state.sorted_df
  st.success(f'Done! Processed {len(df):,} unique rows.')

  counts = df['Provider'].value_counts()
  st.subheader('Clean Leads Breakdown')
  col1, col2, col3, col4 = st.columns(4)
  col1.metric('Google Workspace', counts.get('Google Workspace', 0))
  col2.metric('Microsoft 365', counts.get('Microsoft 365', 0))
  col3.metric('Personal / Free', counts.get('Personal / Free Email', 0))
  col4.metric('Other B2B', counts.get('Other', 0))

  st.subheader('Pre-Bounce & Risk Breakdown')
  r_col1, r_col2, r_col3, r_col4 = st.columns(4)
  hard_bounces = df[df['Bounce_Risk'].str.startswith('Hard Bounce')]
  role_risks = df[df['Bounce_Risk'].str.startswith('High Risk')]
  r_col1.metric(
      'Hard Bounces Caught',
      len(hard_bounces),
      help='Dead domains, typos, parked domains, disposable, syntax errors',
  )
  r_col2.metric(
      'Role / Generic Risk',
      len(role_risks),
      help='info@, sales@, admin@, support@, etc.',
  )
  r_col3.metric('Domain Typos Caught', counts.get('Invalid / Typo Domain', 0))
  r_col4.metric(
      'Parked / Dead Domains',
      counts.get('Invalid / No MX', 0)
      + counts.get('Invalid / Parked Domain', 0),
  )

  st.subheader('Download Your Segmented Lists')
  f_col1, f_col2 = st.columns(2)
  with f_col1:
    exclude_gateways = st.checkbox(
        'Exclude Mimecast / Proofpoint / Barracuda from Google & Microsoft'
        ' downloads',
        value=False,
