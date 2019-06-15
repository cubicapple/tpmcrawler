import pycurl
import io
import re
import json
import fitz
import sys
import os.path
import argparse

from html.parser import HTMLParser


class URLReader():
	def __init__(self):
		self.stream = io.BytesIO()

	def read(self, url, cookies='cookies.txt'):
		c = pycurl.Curl()
		c.setopt(pycurl.COOKIEFILE, cookies)
		c.setopt(c.URL, url)
		c.setopt(c.WRITEDATA, self.stream)
		c.perform()
		c.close()
		return self

	def getbuffer(self):
		return self.stream.getbuffer()

	def decode(self, encoding='UTF-8'):
		return self.stream.getvalue().decode( encoding)

class IssuesCatalogParser( HTMLParser):
	regexp = r'/onlinereader/(?P<issue>\d+)'

	def __init__(self):
	    HTMLParser.__init__(self)
	    self.covertitlelink_level = 0
	    self.span_level = 0
	    self.last_tag = ''
	    self.last_issue = ''

	    self.issues = []

	def handle_starttag( self, tag, attrs):
		self.last_tag = tag

		if tag == 'span':
			self.span_level += 1
			for (attr, value) in attrs:
				if attr == 'class' and value == 'covertitlelink':
					self.covertitlelink_level = self.span_level
		elif tag == 'a':
			if self.covertitlelink_level > 0:
				for (attr, value) in attrs:
					m = re.search( IssuesCatalogParser.regexp, value)
					if attr == 'href' and m:
						self.last_issue = m.group('issue')

	def handle_data(self, data):
 		if self.covertitlelink_level > 0 and self.last_tag == 'a' and self.last_issue != '':
 			self.issues.append( [data, self.last_issue])


	def handle_endtag( self, tag):
		self.last_issue = ''
		if tag != 'span':
			return
		self.span_level -= 1
		if self.span_level < self.covertitlelink_level:
			self.covertitlelink_level = 0

	def parse_url( self, url):
		str = URLReader().read( url).decode()
		self.feed( str)

class MagazineHTMLParser( HTMLParser):

	url_template = 'https://pocketmags.com/onlinereader/html5_reader/false/{:s}'
	# loadMagazine('0b2a6425-51c3-4c61-bb66-e840b282d88b','482bc8c5-a86d-475a-8047-63c82830d76e','false',pageNumber, null,181299, new Analytics(),'GBP');}         
	regexp = r'loadMagazine\(\s*\'(?P<userGuid>(\w|\-)+)\'\s*,\s*\'(?P<issueId>(\w|\-)+)\'\s*,\s*\'(?P<custom>\w+)\'\s*,\s*(?P<pageNumber>\w+)\s*,\s*(?P<null>\w+)\s*,\s*(?P<issue>\w+)\s*'

	def __init__(self, magazine):
		HTMLParser.__init__(self)
		self.magazine = magazine
		self.last_tag = ''

	def handle_starttag( self, tag, attrs):
		self.last_tag = tag

	def handle_data(self, data):
		if self.last_tag == 'script':
			m = re.search( MagazineHTMLParser.regexp, data, re.MULTILINE)
			if m and m.group('issue') == self.magazine.issue:
				self.magazine.userGuid = m.group('userGuid') 
				self.magazine.issueId = m.group('issueId') 
				self.magazine.custom = m.group('custom') 

	def parse( self):
		url = MagazineHTMLParser.url_template.format( self.magazine.issue)
		str = URLReader().read( url).decode()
		self.feed( str)

class Magazine():
	magazine_url_template = 'https://htmlrequest.magazinecloner.com/{:s}/{:s}/{:s}'

	def __init__(self, issue, name):
		self.issue = issue
		self.name = name
		self.userGuid = ''
		self.issueId = ''
		self.custom = '' 

	def get_json(self):
		MagazineHTMLParser(self).parse()
		url = Magazine.magazine_url_template.format( self.userGuid, self.issueId, self.custom)
		self.json = json.loads( URLReader().read( url).decode())	

class PDF:
	def __init__(self, magazine):
		self.magazine = magazine
		self.units = 'mm'
		self.scale = 0.98
		self.page_width = 210
		self.page_height = 297

	def load_image(self, url):
		ext = ''
		content_type = ''

		buffer = URLReader().read( url).getbuffer()
		if buffer[2] == 78 and buffer[3] == 71:
			buffer[0] = 137
			buffer[1] = 80
			content_type += 'image/png'
		else:
			buffer[0] = 255
			buffer[1] = 216
			content_type += 'image/jpeg'

		return content_type, bytes(buffer)


	def read_pages(self, pdf):
		i = 1
		for page in self.magazine.json['pages']:
			content_type, f = self.load_image(page['page'][0]['url'])
			img = fitz.open( stream = f, filetype = content_type)
			rect = img[0].rect
			pdf_bytes = img.convertToPDF()
			img.close()
			page = pdf.newPage( width = rect.width, height = rect.height)
			page.showPDFpage( rect, fitz.open( 'pdf', pdf_bytes), 0)

			sys.stdout.write('.')
			sys.stdout.flush()

			if i%10 == 0:
				print()
			i += 1

		print()

	def create_toc(self, pdf):
		toc = []
		for entry in self.magazine.json['issueContent']:
			pageNumber = entry['pageNumber'] + 1
			header = entry['header']
			toc.append([1, header, pageNumber])


		pdf.setToC( toc)

	def create_pdf(self):
		name = self.magazine.name + '.pdf'
		
		pdf = fitz.open()
		print( 'Creating pages')
		self.read_pages( pdf)
		print( 'Creating ToC')
		self.create_toc( pdf)

		pdf.save( name)


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description='Load "The Pianist" issues as PDFs.')
	parser.add_argument( '-n', '--name', help = 'Issue name for loading. If not present, will try to load all new issues.')
	parser.add_argument( '--load-json', action='store_true', help='If specified, the issue JSON will be loaded instead of PDF.')
	args = parser.parse_args()

	ext = '.json' if args.load_json else '.pdf'

	url = 'https://pocketmags.com/membersarea/myissues/684'

	p = IssuesCatalogParser()
	p.parse_url( url)

	count = 0
	for name, issue in p.issues:
		if args.name and name != args.name:
			continue

		count += 1

		filename = name + ext
		if os.path.isfile( filename):
			print( '{:s} already exists'.format( filename))
		else:
			print( 'Loading issue {:s}, {:s}'.format( issue, name))
			m = Magazine( issue, name)
			m.get_json()
			if args.load_json:
				with open(filename, 'w') as f:
					json.dump( m.json, f)
			else:
				PDF(m).create_pdf()
			print( '{:s} saved'.format( filename))


	if args.name and count == 0:
		print( 'Issue named "{:s}" not found on server'.format(args.name))

