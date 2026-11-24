from concurrent.futures import ThreadPoolExecutor
import re
import dns.resolver
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title='Lead Email Provider & Enrichment Sorter',
    page_icon='📧',
    layout='wide',
)
st.title('📧 Lead Email Provider & Enrichment Sorter')
st.write(
    'Upload a CSV or TXT file to clean syntax/disposable emails, sort B2B'
    ' providers, detect security gateways, and extract names.'
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
    return ('Invalid / Syntax Error', 'None')

  if domain in DISPOSABLE_DOMAINS:
    return ('Disposable / Burner', 'None')

  if domain in FREE_DOMAINS:
    return ('Personal / Free Email', 'None')

  try:
    mx_records = dns.resolver.resolve(domain, 'MX', lifetime=3)
    mx_string = ' '.join([str(r.exchange).lower() for r in mx_records])
    gateway = detect_gateway(mx_string)

    if 'google.com' in mx_string or 'googlemail.com' in mx_string:
      return ('Google Workspace', gateway)
    elif 'outlook.com' in mx_string:
      return ('Microsoft 365', gateway)

    # Fallback: Check SPF (TXT) records if hidden behind a security gateway
    txt_records = dns.resolver.resolve(domain, 'TXT', lifetime=3)
    txt_string = ' '.join([str(r).lower() for r in txt_records])

    if '_://google.com' in txt_string:
      return ('Google Workspace', gateway)
    elif '://outlook.com' in txt_string:
      return ('Microsoft 365', gateway)

    return ('Other', gateway)
  except Exception:
    return ('Invalid / No MX', 'None')


def extract_first_name(email):
  try:
    if not is_valid_syntax(email):
      return ''
    local = str(email).split('@')[0].strip().lower()
    role_prefixes = {
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
    }
    parts = re.split(r'[._\-0-9]+', local)
    first_part = parts[0] if parts else ''
    if (
        len(parts) >= 2
        and len(first_part) >= 2
        and first_part not in role_prefixes
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
        or '.' not in domain
    ):
      return ''
    name = domain.split('.')[0]
    return name.replace('-', ' ').title()
  except Exception:
    return ''


# Initialize session state storage
if 'sorted_df' not in st.session_state:
  st.session_state.sorted_df = None
if 'last_file_id' not in st.session_state:
  st.session_state.last_file_id = None

uploaded_file = st.file_uploader(
    'Upload your leads file (CSV or TXT)', type=['csv', 'txt']
)

if uploaded_file is not None:
  # Clear saved results if user uploads a brand new file
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

  if st.button('Clean, Sort & Enrich Leads', type='primary'):
    with st.spinner('Cleaning syntax, checking MX/SPF, and extracting info...'):
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

      def get_provider(row):
        if not row['_valid_syntax']:
          return 'Invalid / Syntax Error'
        return domain_results.get(row['_domain'], ('Invalid / No MX', 'None'))[0]

      def get_gateway(row):
        if not row['_valid_syntax']:
          return 'None'
        return domain_results.get(row['_domain'], ('Invalid / No MX', 'None'))[1]

      df['Provider'] = df.apply(get_provider, axis=1)
      df['Security_Gateway'] = df.apply(get_gateway, axis=1)
      df['Extracted_First_Name'] = df[email_col].apply(extract_first_name)
      df['Extracted_Company'] = df['_domain'].apply(extract_company)

      df.drop(columns=['_valid_syntax', '_domain'], inplace=True)

      # Save sorted dataframe in memory so downloads don't wipe it
      st.session_state.sorted_df = df

# Display results from session_state so they stay visible across multiple downloads
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

  st.subheader('Removed / Invalid Breakdown')
  inv_col1, inv_col2, inv_col3 = st.columns(3)
  inv_col1.metric(
      'Invalid / Syntax Error', counts.get('Invalid / Syntax Error', 0)
  )
  inv_col2.metric('Invalid / No MX', counts.get('Invalid / No MX', 0))
  inv_col3.metric('Disposable / Burner', counts.get('Disposable / Burner', 0))

  st.subheader('Download Your Segmented Lists')
  exclude_gateways = st.checkbox(
      'Exclude Mimecast / Proofpoint / Barracuda leads from Google & Microsoft'
      ' download files',
      value=False,
  )

  if exclude_gateways:
    g_df = df[
        (df['Provider'] == 'Google Workspace')
        & (df['Security_Gateway'] == 'None')
    ]
    m_df = df[
        (df['Provider'] == 'Microsoft 365')
        & (df['Security_Gateway'] == 'None')
    ]
  else:
    g_df = df[df['Provider'] == 'Google Workspace']
    m_df = df[df['Provider'] == 'Microsoft 365']

  p_df = df[df['Provider'] == 'Personal / Free Email']
  o_df = df[df['Provider'] == 'Other']
  invalid_df = df[
      df['Provider'].isin(
          ['Invalid / Syntax Error', 'Invalid / No MX', 'Disposable / Burner']
      )
  ]

  d_col1, d_col2, d_col3, d_col4, d_col5, d_col6 = st.columns(6)

  with d_col1:
    st.download_button(
        '⬇️ All Rows',
        df.to_csv(index=False).encode('utf-8'),
        'all_processed_leads.csv',
        'text/csv',
        key='dl_all',
    )
  with d_col2:
    st.download_button(
        f'⬇️ Google ({len(g_df)})',
        g_df.to_csv(index=False).encode('utf-8'),
        'google_b2b_leads.csv',
        'text/csv',
        key='dl_google',
    )
  with d_col3:
    st.download_button(
        f'⬇️ Microsoft ({len(m_df)})',
        m_df.to_csv(index=False).encode('utf-8'),
        'microsoft_b2b_leads.csv',
        'text/csv',
        key='dl_ms',
    )
  with d_col4:
    st.download_button(
        f'⬇️ Personal ({len(p_df)})',
        p_df.to_csv(index=False).encode('utf-8'),
        'personal_email_leads.csv',
        'text/csv',
        key='dl_personal',
    )
  with d_col5:
    st.download_button(
        f'⬇️ Other ({len(o_df)})',
        o_df.to_csv(index=False).encode('utf-8'),
        'other_b2b_leads.csv',
        'text/csv',
        key='dl_other',
    )
  with d_col6:
    st.download_button(
        f'⬇️ Invalid/Syntax ({len(invalid_df)})',
        invalid_df.to_csv(index=False).encode('utf-8'),
        'invalid_and_syntax_errors.csv',
        'text/csv',
        key='dl_invalid',
    )

  st.subheader('Data Preview')
  tab1, tab2 = st.tabs([
      f'All Leads ({len(df)})',
      f'⚠️ Invalid & Syntax Errors ({len(invalid_df)})',
  ])
  with tab1:
    st.dataframe(df.head(50), use_container_width=True)
  with tab2:
    if len(invalid_df) > 0:
      st.dataframe(invalid_df, use_container_width=True)
    else:
      st.info('No invalid or syntax errors found in this list!')
