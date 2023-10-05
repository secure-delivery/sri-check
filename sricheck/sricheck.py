#!/usr/bin/env python3

import argparse
import base64
import hashlib
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

def generate_sha(remote_resource_tag):
    tag = remote_resource_tag['tag']
    resource_data = requests.get(remote_resource_tag['tag'][remote_resource_tag['attr']]).content
    integrity_checksum = base64.b64encode(hashlib.sha384(resource_data).digest()).decode('utf-8')
    tag['integrity'] = f"sha384-{integrity_checksum}"
    tag['crossorigin'] = 'anonymous'

    return tag

class SRICheck:
    def __init__(self, url, browser=False, headers={}, whitelisted_hosts = [], all=False):
        self.url = url
        self.browser = browser
        self.headers = headers
        self.whitelisted_hosts = whitelisted_hosts
        self.all = all

    def is_whitelisted(self, netloc):
        try:
            self.whitelisted_hosts.index(netloc)
        except ValueError:
            return False
        else:
            return True


    def get_html(self):
        if self.browser:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options

            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.experimental_options["prefs"] = {
                "profile.default_content_settings": {
                    "images": 2
                }
            }

            browser = webdriver.Chrome("chromedriver", options=chrome_options)

            def interceptor(request):
                request.headers.update(self.headers)

            browser.request_interceptor = interceptor

            browser.get(self.url)
            return browser.page_source
        else:
            # file deepcode ignore Ssrf: The purpose of the script is to parse remote URLs from the CLI
            return requests.get(self.url, headers=self.headers).content


    def get_remote_resource_tags(self, html):
        soup = BeautifulSoup(html, 'lxml')

        resource_tags = []
        remote_resource_tags = []

        if self.all:
            script_tags = [tag for tag in soup.find_all(['script'], attrs={'src':True})]
            link_tags = [tag for tag in soup.find_all(['link'], attrs={'href':True})]
            resource_tags.extend(script_tags)
            resource_tags.extend(link_tags)
        else:
            script_tags = [tag for tag in soup.find_all(['script'], attrs={'src':True, 'integrity':None})]
            link_tags = [tag for tag in soup.find_all(['link'], attrs={'href':True, 'integrity':None})]
            resource_tags.extend(script_tags)
            resource_tags.extend(link_tags)

        if len(resource_tags) > 0:
            parsed_source_url = urlparse(self.url)

            for resource_tag in resource_tags:
                attribute = ""
                for potential_attribute in ['src', 'href']:
                    if potential_attribute in resource_tag.attrs:
                        attribute = potential_attribute

                if re.search('^//', resource_tag[attribute]):
                    resource_tag[attribute] = parsed_source_url.scheme + ':' + resource_tag[attribute]

                parsed_tag = urlparse(resource_tag[attribute])
                if parsed_tag.scheme in {'http', 'https'}:
                    if self.is_whitelisted(parsed_tag.netloc) is False:
                        remote_resource_tags.append({'tag': resource_tag, 'attr': attribute})

        return remote_resource_tags

    def run(self):
        html = self.get_html()
        remote_resource_tags = self.get_remote_resource_tags(html)

        return remote_resource_tags

def cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("-g", "--generate", help="Generate sha384 hashes for resources", action="store_true")
    parser.add_argument("-a", "--all", help="Output detected script/link tags regardless of SRI status", action="store_true")
    parser.add_argument("-b", "--browser", help="Use headless browser to retrieve page and run client side rendering", action="store_true")
    parser.add_argument("-H", "--header", help="HTTP header value to send with the request. Specify multiple times if needed", action="append")
    parser.add_argument("-i", "--ignore", help="Ignore a host (in netloc format - e.g. www.4armed.com) when checking for SRI. Specify multiple times if needed", action="append")
    parser.add_argument("url", help="Target URL to check for SRI")
    args = parser.parse_args()

    headers = {}
    if args.header:
        for header in args.header:
            k, v = header.split(": ")
            headers[k] = v

    # hosts we will ignore (in netloc format), in addition to the target URL
    whitelisted_hosts = [
        "fonts.googleapis.com", # does not use versioning so can't realistically use SRI
        "js.hs-scripts.com", # does not use versioning so can't realistically use SRI
        urlparse(args.url).netloc
    ]

    if args.ignore:
        for host in args.ignore:
            whitelisted_hosts.append(host)

    s = SRICheck(url=args.url, browser=args.browser, headers=headers, whitelisted_hosts=whitelisted_hosts, all=args.all)
    remote_resource_tags = s.run()

    if len(remote_resource_tags) > 0:
        for remote_resource_tag in remote_resource_tags:
            if args.generate:
                print(generate_sha(remote_resource_tag))
            else:
                print(remote_resource_tag['tag'])
    else:
        print("[*] No resource tags found without integrity attribute")

if __name__== "__main__":
    cli()