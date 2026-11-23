from concurrent.futures import ThreadPoolExecutor
import dns.resolver
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title='Lead Email Provider Sorter', page_icon='📧', layout='wide'
)
st.title('📧 Lead Email Provider Sorter')
st.write(
    'Upload a CSV file containing an **email** column to sort leads into'
    ' Google Workspace, Microsoft 365, or Others.'
)


def check_domain_advanced(domain):
  try:
    mx_records = dns.resolver.resolve(domain, 'MX', lifetime=3)
    mx_string = ' '.join([str(r.exchange).lower() for r in mx_records])

    if 'google.com' in mx_string or 'googlemail.com' in mx_string:
      return 'Google Workspace'
    elif 'outlook.com' in mx_string:
      return 'Microsoft 365'

    # Check SPF records if hidden behind a security filter
    txt_records = dns.resolver.resolve(domain, 'TXT', lifetime=3)
    txt_string = ' '.join([str(r).lower() for r in txt_records])

    if '_://google.com' in txt_string:
      return 'Google Workspace'
    elif '://outlook.com' in txt_string:
      return 'Microsoft 365'

    return 'Other'
  except Exception:
    return 'Invalid / No MX'


uploaded_file = st.file_uploader('Upload your leads CSV', type='csv')

if uploaded_file is not None:
  df = pd.read_csv(uploaded_file)
  email_col = next(
      (col for col in df.columns if col.strip().lower() == 'email'), None
  )

  if not email_col:
    st.error("Error: Your CSV must have a column named 'email'.")
  else:
    if st.button('Sort Leads', type='primary'):
      with st.spinner('Sorting your leads...'):
        # Remove duplicate emails automatically
        df = df.drop_duplicates(subset=[email_col]).copy()

        # Extract unique domains
        df['_domain'] = (
            df[email_col]
            .astype(str)
            .apply(lambda x: x.split('@')[-1].strip().lower() if '@' in x else '')
        )
        unique_domains = [d for d in df['_domain'].unique() if d]

        # Check domains fast
        with ThreadPoolExecutor(max_workers=25) as executor:
          domain_results = dict(
              zip(
                  unique_domains,
                  executor.map(check_domain_advanced, unique_domains),
              )
          )

        df['Provider'] = df['_domain'].map(domain_results).fillna('Invalid / No MX')
        df.drop(columns=['_domain'], inplace=True)

      st.success(f'Done! Sorted {len(df):,} unique leads.')

      # Show numbers
      counts = df['Provider'].value_counts()
      col1, col2, col3, col4 = st.columns(4)
      col1.metric('Google Workspace', counts.get('Google Workspace', 0))
      col2.metric('Microsoft 365', counts.get('Microsoft 365', 0))
      col3.metric('Other', counts.get('Other', 0))
      col4.metric('Invalid / No MX', counts.get('Invalid / No MX', 0))

      # Download buttons
      st.subheader('Download Your Lists')
      d_col1, d_col2, d_col3, d_col4 = st.columns(4)

      with d_col1:
        st.download_button(
            '⬇️ All Sorted Leads',
            df.to_csv(index=False).encode('utf-8'),
            'all_sorted_leads.csv',
            'text/csv',
        )
      with d_col2:
        g_df = df[df['Provider'] == 'Google Workspace']
        st.download_button(
            '⬇️ Google Workspace Only',
            g_df.to_csv(index=False).encode('utf-8'),
            'google_leads.csv',
            'text/csv',
        )
      with d_col3:
        m_df = df[df['Provider'] == 'Microsoft 365']
        st.download_button(
            '⬇️ Microsoft 365 Only',
            m_df.to_csv(index=False).encode('utf-8'),
            'microsoft_leads.csv',
            'text/csv',
        )
      with d_col4:
        o_df = df[df['Provider'] == 'Other']
        st.download_button(
            '⬇️ Others Only',
            o_df.to_csv(index=False).encode('utf-8'),
            'other_leads.csv',
            'text/csv',
        )

      st.subheader('Preview')
      st.dataframe(df.head(15), use_container_width=True)
