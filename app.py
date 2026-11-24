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
    'Upload a CSV or TXT file to sort B2B providers, separate personal emails,'
    ' detect security gateways, and extract names.'
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
    return ('Invalid / No MX', 'None')

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
    local = str(email).split('@')[0].strip().lower()
    # Ignore generic role-based prefixes
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
    first_part = re.split(r'[._\-0-9]+', local)[0]
    if len(first_part) >= 2 and first_part not in role_prefixes:
      return first_part.capitalize()
    return ''
  except Exception:
    return ''


def extract_company(domain):
  try:
    if not domain or domain in FREE_DOMAINS or '.' not in domain:
      return ''
    # Take the main domain name before the TLD (e.g., acme.com -> Acme)
    name = domain.split('.')[0]
    return name.replace('-', ' ').title()
  except Exception:
    return ''


uploaded_file = st.file_uploader(
    'Upload your leads file (CSV or TXT)', type=['csv', 'txt']
)

if uploaded_file is not None:
  if uploaded_file.name.lower().endswith('.txt'):
    lines = [
        line.decode('utf-8', errors='ignore').strip()
        for line in uploaded_file.readlines()
    ]
    df = pd.DataFrame({'email': [l for l in lines if '@' in l]})
    email_col = 'email'
  else:
    df = pd.read_csv(uploaded_file)
    default_idx = next(
        (i for i, col in enumerate(df.columns) if 'email' in col.lower()), 0
    )
    email_col = st.selectbox(
        'Select which column contains your email addresses:',
        df.columns,
        index=default_idx,
    )

  exclude_gateways = st.checkbox(
      'Exclude Mimecast / Proofpoint / Barracuda leads from Google & Microsoft'
      ' download files (Recommended for cold email)',
      value=False,
  )

  if st.button('Sort & Enrich Leads', type='primary'):
    with st.spinner('Analyzing MX/SPF records, gateways, and extracting names...'):
      df = df.drop_duplicates(subset=[email_col]).copy()
      df[email_col] = df[email_col].astype(str).str.strip()

      df['_domain'] = df[email_col].apply(
          lambda x: x.split('@')[-1].strip().lower() if '@' in x else ''
      )
      unique_domains = [d for d in df['_domain'].unique() if d]

      with ThreadPoolExecutor(max_workers=25) as executor:
        domain_results = dict(
            zip(unique_domains, executor.map(analyze_domain, unique_domains))
        )

      df['Provider'] = df['_domain'].map(
          lambda d: domain_results.get(d, ('Invalid / No MX', 'None'))[0]
      )
      df['Security_Gateway'] = df['_domain'].map(
          lambda d: domain_results.get(d, ('Invalid / No MX', 'None'))[1]
      )
      df['Extracted_First_Name'] = df[email_col].apply(extract_first_name)
      df['Extracted_Company'] = df['_domain'].apply(extract_company)

      df.drop(columns=['_domain'], inplace=True)

    st.success(f'Done! Processed {len(df):,} unique leads.')

    # Metrics Row
    counts = df['Provider'].value_counts()
    gateway_count = len(df[df['Security_Gateway'] != 'None'])

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric('Google Workspace', counts.get('Google Workspace', 0))
    col2.metric('Microsoft 365', counts.get('Microsoft 365', 0))
    col3.metric('Personal / Free', counts.get('Personal / Free Email', 0))
    col4.metric('Other B2B', counts.get('Other', 0))
    col5.metric('Behind Gateway', gateway_count)

    # Download Section
    st.subheader('Download Your Segmented Lists')
    d_col1, d_col2, d_col3, d_col4, d_col5 = st.columns(5)

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

    with d_col1:
      st.download_button(
          '⬇️ All Enriched Leads',
          df.to_csv(index=False).encode('utf-8'),
          'all_enriched_leads.csv',
          'text/csv',
      )
    with d_col2:
      st.download_button(
          f'⬇️ Google B2B ({len(g_df)})',
          g_df.to_csv(index=False).encode('utf-8'),
          'google_b2b_leads.csv',
          'text/csv',
      )
    with d_col3:
      st.download_button(
          f'⬇️ Microsoft B2B ({len(m_df)})',
          m_df.to_csv(index=False).encode('utf-8'),
          'microsoft_b2b_leads.csv',
          'text/csv',
      )
    with d_col4:
      st.download_button(
          f'⬇️ Personal/Free ({len(p_df)})',
          p_df.to_csv(index=False).encode('utf-8'),
          'personal_email_leads.csv',
          'text/csv',
      )
    with d_col5:
      st.download_button(
          f'⬇️ Other B2B ({len(o_df)})',
          o_df.to_csv(index=False).encode('utf-8'),
          'other_b2b_leads.csv',
          'text/csv',
      )

    st.subheader('Data Preview')
    st.dataframe(df.head(20), use_container_width=True)
