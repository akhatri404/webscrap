import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import pdfplumber
from tabula import read_pdf
import io

# Function to scrape tables from a webpage (URL)
def scrape_table_data_from_url(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml')
        
        # Check if the content is HTML
        if "text/html" not in response.headers.get('Content-Type', ''):
            st.error("The provided URL does not contain HTML content.")
            return None
        
        # Extract all tables
        tables = soup.find_all('table')
        if not tables:
            st.error("No tables found on the webpage.")
            return None

        dfs = [pd.read_html(str(table))[0] for table in tables]
        return dfs
    
    except requests.exceptions.MissingSchema:
        st.error("Invalid URL. Please enter a valid URL starting with http:// or https://.")
        return None
    
    except requests.exceptions.Timeout:
        st.error("The request timed out. Please try again later.")
        return None

    except requests.exceptions.ConnectionError:
        st.error("Failed to connect to the webpage. Please check the URL or your internet connection.")
        return None

    except requests.exceptions.HTTPError as http_err:
        st.error(f"HTTP error occurred: {http_err}")
        return None

    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
        return None

# Function to extract text data from PDF
def extract_text_from_pdf(pdf_file):
    text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text += page.extract_text()
    return text

# Function to extract table data from PDF using tabula-py
def extract_tables_from_pdf(pdf_file):
    try:
        tables = read_pdf(pdf_file, pages='all', multiple_tables=True)
        return tables
    except Exception as e:
        st.error(f"Error extracting tables: {str(e)}")
        return None

# Function to convert DataFrames to an Excel file with multiple sheets
def to_excel(dfs, source_type='table'):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        for i, df in enumerate(dfs):
            df.to_excel(writer, index=False, sheet_name=f"{source_type}_Sheet{i+1}")
    return output.getvalue()

# Main function for the Streamlit app
def main():
    st.title("Web & PDF Scraper for Tabular Data")
    st.write("=======================")
    st.write("Developed By Er Ashish K.C. (Khatri)")
    
    # Option for users to choose scraping method
    option = st.selectbox("Select the data source", ["Web Page (URL)", "PDF File"])
    
    if option == "Web Page (URL)":
        url = st.text_input("Enter the URL of the webpage:")
        
        if url:
            dfs = scrape_table_data_from_url(url)
            
            if dfs:
                st.write(f"Found {len(dfs)} table(s) on the webpage.")
                
                # Show each table
                for i, df in enumerate(dfs):
                    st.write(f"Table {i+1}")
                    st.dataframe(df)
                
                # Download tables as Excel
                excel_data = to_excel(dfs, source_type='web')
                st.download_button(
                    label="Download Tables as Excel",
                    data=excel_data,
                    file_name='webpage_tables.xlsx',
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                )

                # Download tables as CSV (one per table)
                for i, df in enumerate(dfs):
                    csv_data = df.to_csv(index=False)
                    st.download_button(
                        label=f"Download Table {i+1} as CSV",
                        data=csv_data,
                        file_name=f'web_table_{i+1}.csv',
                        mime='text/csv'
                    )
    
    elif option == "PDF File":
        uploaded_file = st.file_uploader("Upload a PDF file", type="pdf")
        
        if uploaded_file is not None:
            # Extract text data from PDF
            st.write("Extracting text data...")
            text_data = extract_text_from_pdf(uploaded_file)
            if text_data:
                st.text_area("Extracted Text", text_data, height=200)
            
            # Extract table data from PDF
            st.write("Extracting tables from PDF...")
            tables = extract_tables_from_pdf(uploaded_file)
            if tables:
                for i, table in enumerate(tables):
                    st.write(f"Table {i+1}")
                    st.dataframe(table)

                # Download tables as Excel
                excel_data = to_excel(tables, source_type='pdf')
                st.download_button(
                    label="Download Tables as Excel",
                    data=excel_data,
                    file_name='pdf_tables.xlsx',
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                )

                # Download tables as CSV (one per table)
                for i, table in enumerate(tables):
                    csv_data = table.to_csv(index=False)
                    st.download_button(
                        label=f"Download Table {i+1} as CSV",
                        data=csv_data,
                        file_name=f'pdf_table_{i+1}.csv',
                        mime='text/csv'
                    )

if __name__ == "__main__":
    main()
