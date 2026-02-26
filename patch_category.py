with open("web_app/templates/category_info.html", "r") as f:
    content = f.read()

new_content = content.replace("""    <section class="card">
      <h2>Field Guide</h2>""", """    {% if faqs %}
      <section class="card">
        <h2>Frequently Asked Questions</h2>
        <dl class="faq-list">
          {% for faq in faqs %}
            <div class="faq-item">
              <dt>{{ faq.q }}</dt>
              <dd>{{ faq.a }}</dd>
            </div>
          {% endfor %}
        </dl>
      </section>
    {% endif %}

    {% if comparison %}
      <section class="card">
        <h2>{{ comparison.title }}</h2>
        <div class="table-wrap">
          <table class="bots-table">
            <thead>
              <tr>
                {% for header in comparison.headers %}
                  <th>{{ header }}</th>
                {% endfor %}
              </tr>
            </thead>
            <tbody>
              {% for row in comparison.rows %}
                <tr>
                  {% for cell in row %}
                    <td>{{ cell }}</td>
                  {% endfor %}
                </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </section>
    {% endif %}

    {% if checklist %}
      <section class="card">
        <h2>Implementation Checklist</h2>
        <ul class="checks-list">
          {% for item in checklist %}
            <li>{{ item }}</li>
          {% endfor %}
        </ul>
      </section>
    {% endif %}

    <section class="card">
      <h2>Field Guide</h2>""")

with open("web_app/templates/category_info.html", "w") as f:
    f.write(new_content)
